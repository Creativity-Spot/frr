#!/usr/bin/env python

# Copyright 2018, LabN Consulting, L.L.C.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; see the file COPYING; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA

#
# want_rd_routes = [
#     {'rd':'10:1', 'p':'5.1.0.0/24', 'n':'1.1.1.1', 'bp': True},
#     {'rd':'10:1', 'p':'5.1.0.0/24', 'n':'1.1.1.1', 'bp': False},
#
#     {'rd':'10:3', 'p':'5.1.0.0/24', 'n':'3.3.3.3'},
# ]
#
# ribRequireVpnRoutes('r2','Customer routes',want_rd_routes)
#
# want_unicast_routes = [
#     {'p':'5.1.0.0/24', 'n':'1.1.1.1'},
# ]
#
# ribRequireUnicastRoutes('r1','ipv4','r1-cust1','Customer routes in vrf',want_unicast_routes)
# ribRequireUnicastRoutes('r1','ipv4','','Customer routes in default',want_unicast_routes)
#

from lib.lutil import luCommand, luResult, LUtil
import json
import re
import time

# gpz: get rib in json form and compare against desired routes
class BgpRib:
    def log(self, str):
        LUtil.log("BgpRib: " + str)

    def routes_include_wanted(self, pfxtbl, want, debug):
        # helper function to RequireVpnRoutes
        for pfx in pfxtbl.keys():
            if debug:
                self.log("trying pfx %s" % pfx)
            if "exist" in want and want["exist"] == False:
                if pfx == want["p"]:
                    if debug:
                        self.log("unexpected route: pfx=" + want["p"])
                    return 0
                if debug:
                    self.log("unwant pfx=" + want["p"] + ", not " + pfx)
                continue
            elif pfx != want["p"]:
                if debug:
                    self.log("want pfx=" + want["p"] + ", not " + pfx)
                continue
            if debug:
                self.log("have pfx=%s" % pfx)
            for r in pfxtbl[pfx]:
                bp = r.get("bestpath", False)
                if debug:
                    self.log("trying route %s bp=%s" % (r, bp))
                nexthops = r["nexthops"]
                for nh in nexthops:
                    if debug:
                        self.log("trying nh %s" % nh["ip"])
                    if nh["ip"] == want["n"]:
                        if debug:
                            self.log("found %s" % want["n"])
                        if bp == want.get("bp", bp):
                            return 1
                        elif debug:
                            self.log("bestpath mismatch %s != %s" % (bp, want["bp"]))
                    else:
                        if debug:
                            self.log("want nh=" + want["n"] + ", not " + nh["ip"])
            if debug:
                self.log("missing route: pfx=" + want["p"] + ", nh=" + want["n"])
            return 0
        if "exist" in want and want["exist"] == False:
            return 1
        return 0

    def RequireVpnRoutes(self, target, title, wantroutes, retry=0, wait=1, debug=0):
        import json

        logstr = "RequireVpnRoutes " + str(wantroutes)
        retry += 1
        while retry:
            retry -= 1
            # non json form for humans
            luCommand(
                target,
                'vtysh -c "show bgp ipv4 vpn"',
                ".",
                "None",
                "Get VPN RIB (non-json)",
            )
            ret = luCommand(
                target,
                'vtysh -c "show bgp ipv4 vpn json"',
                ".*",
                "None",
                "Get VPN RIB (json)",
            )
            if re.search(r"^\s*$", ret):
                # degenerate case: empty json means no routes
                if len(wantroutes) > 0:
                    luResult(target, False, title, logstr)
                    return
                luResult(target, True, title, logstr)
            rib = json.loads(ret)
            rds = rib["routes"]["routeDistinguishers"]
            for want in wantroutes:
                found = 0
                if debug:
                    self.log("want rd %s" % want["rd"])
                for rd in rds.keys():
                    if rd != want["rd"]:
                        continue
                    if debug:
                        self.log("found rd %s" % rd)
                    table = rds[rd]
                    if self.routes_include_wanted(table, want, debug):
                        found = 1
                        break
                if not found:
                    if retry:
                        break
                    luResult(target, False, title, logstr)
                    return
            if not found and retry:
                time.sleep(wait)
                continue
            luResult(target, True, title, logstr)
            break

    def RequireUnicastRoutes(
        self, target, afi, vrf, title, wantroutes, retry=0, wait=1, debug=0
    ):
        logstr = "RequireUnicastRoutes %s" % str(wantroutes)
        vrfstr = ""
        if vrf != "":
            vrfstr = "vrf %s" % (vrf)

        if (afi != "ipv4") and (afi != "ipv6"):
            self.log("ERROR invalid afi")

        retry += 1
        while retry:
            retry -= 1
            cmdstr = "show bgp %s %s unicast" % (vrfstr, afi)
            # non json form for humans
            cmd = 'vtysh -c "%s"' % cmdstr
            luCommand(
                target, cmd, ".", "None", "Get %s %s RIB (non-json)" % (vrfstr, afi)
            )
            cmd = 'vtysh -c "%s json"' % cmdstr
            ret = luCommand(
                target, cmd, ".*", "None", "Get %s %s RIB (json)" % (vrfstr, afi)
            )
            if re.search(r"^\s*$", ret):
                # degenerate case: empty json means no routes
                if len(wantroutes) > 0:
                    luResult(target, False, title, logstr)
                    return
                luResult(target, True, title, logstr)
            rib = json.loads(ret)
            try:
                table = rib["routes"]
                # KeyError: 'routes' probably means missing/bad VRF
            except KeyError as err:
                if vrf != "":
                    errstr = "-script ERROR: check if wrong vrf (%s)" % (vrf)
                else:
                    errstr = "-script ERROR: check if vrf missing"
                if retry:
                    time.sleep(wait)
                    continue
                luResult(target, False, title + errstr, logstr)
                return
            # if debug:
            #    self.log("table=%s" % table)
            for want in wantroutes:
                if debug:
                    self.log("want=%s" % want)
                if not self.routes_include_wanted(table, want, debug):
                    if retry:
                        time.sleep(wait)
                        continue
                    luResult(target, False, title, logstr)
                    return
            luResult(target, True, title, logstr)
            break


BgpRib = BgpRib()


def bgpribRequireVpnRoutes(target, title, wantroutes, retry=0, wait=1, debug=0):
    BgpRib.RequireVpnRoutes(target, title, wantroutes, retry, wait, debug)


def bgpribRequireUnicastRoutes(
    target, afi, vrf, title, wantroutes, retry=0, wait=1, debug=0
):
    BgpRib.RequireUnicastRoutes(target, afi, vrf, title, wantroutes, retry, wait, debug)
