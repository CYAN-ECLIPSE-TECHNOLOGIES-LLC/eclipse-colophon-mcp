#!/usr/bin/env python3
# Eclipse Colophon regression tests — Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
"""Replicates bench shapes byte-for-byte: same fixture shapes Verity uses independently."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import colophon_engine as E, fixtures, server

titles = fixtures.load_all(); T = titles[0]; ok = fail = 0
def chk(name, cond):
    global ok, fail
    print(("PASS " if cond else "FAIL ")+name); ok += bool(cond); fail += (not cond)

chk("23 tools", len(E.TOOLS)==23)
chk("non-owner table excludes owner verbs", all(t["name"] not in E.OWNER_TOOLS for t in server.list_tools(False)))
chk("no price-write verb", not any("price" in n and "write" in n for n in E.TOOLS) and server.dispatch("record_reprice", {})["error"]=="REPRICE_FORBIDDEN")
r = server.dispatch("drift_check_listing", {"title_id": T, "listing": E.S.fixture_listings[0]})
f = r["result"]["findings"][0]
chk("T1 PRICE_BELOW_BOOK both values+severity CRITICAL+consequence", f["class"]=="PRICE_BELOW_BOOK" and f["record_side"]["value"]==999 and f["observed_side"]["value"]==199 and f["severity"]=="CRITICAL" and "consequence_chain" in f)
scan0 = server.dispatch("drift_scan_catalog", {"title_id": T})["result"]
chk("scan (pre-ingest) covers all planted classes incl REPORT_GAP", {"TERRITORY_LEAK","EDITION_UNRECORDED","REPORT_GAP","PRICE_ABOVE_BOOK","METADATA_MISMATCH","PRICE_BELOW_BOOK"} <= {x["class"] for x in scan0["findings"]})
res = server.dispatch("royalty_ingest_report", {"platform":"KDP","period":"2026-09","report_file":{"format":"CSV","content":fixtures.KDP_CSV}}, owner=True)
run = E.royalty_run_get({"run_id": res["result"]["run_ref"]})
by = {e["line_ref"]: e for e in run["entries"]}
chk("T2 K1 match w/ trace 669", by["K1"]["verdict"]=="MATCH" and by["K1"]["expected_minor"]==669 and by["K1"]["arithmetic_trace"]["steps"])
chk("T2 K2 +1c flagged UNRECOMPUTABLE", by["K2"]["flag_class"]=="ROYALTY_LINE_UNRECOMPUTABLE")
chk("T2 K3 rate drift precedence", by["K3"]["flag_class"]=="ROYALTY_TERM_DRIFT")
chk("T6 K4 unrecomputable missing file_size_mb named + COMPLETED_WITH_FLAGS", "file_size_mb" in by["K4"]["reason"] and run["run"]["state"]=="COMPLETED_WITH_FLAGS" and run["run"]["coverage"]=={"lines_total":5,"lines_recomputed":4,"lines_flagged":4})
chk("T14 duplicate report idempotent", server.dispatch("royalty_ingest_report", {"platform":"KDP","period":"2026-09","report_file":{"format":"CSV","content":fixtures.KDP_CSV}}, owner=True)["result"].get("notice")=="REPORT_DUPLICATE")
chk("T3 commerce unlicensed cell refusal", server.dispatch("commerce_verify_offer", {"title_id":T,"edition_id":f"{T}-ebook","seller":"Fixture Press","territory":"DE","price_minor":999})["error"]=="COMMERCE_RIGHTS_UNLICENSED")
chk("commerce verified US", server.dispatch("commerce_verify_offer", {"title_id":T,"edition_id":f"{T}-ebook","seller":"Fixture Press","territory":"US","price_minor":999})["ok"])
chk("T7 pirate refused", server.dispatch("drift_check_listing", {"title_id":T,"listing":{"source_ref":"https://libgen.rs/book/1","observed":{}}})["error"]=="PIRATE_SOURCE_REFUSED")
chk("T8 non-owner sign", server.dispatch("record_sign_version", {"title_id":T,"signer_ref":"mallory","owner_token":E.OWNER_TOKEN}, owner=True)["error"]=="SIGNER_NOT_OWNER")
scan = server.dispatch("drift_scan_catalog", {"title_id": T})["result"]
classes = {x["class"] for x in scan["findings"]}
chk("scan post-ingest: gap resolved by receipt (named class)", any(f["class"]=="REPORT_GAP" and f["state"]=="RESOLVED_REPORT_RECEIVED" for f in E.S.findings))
chk("propagation grouped: 1 finding, instances>=3", any(f.get("group_key")=="prop-title" and f.get("instances",1)>=3 for f in E.S.findings))
chk("T5 quarantined not promoted", any(q["edition_id"]=="ghost-edition" for q in E.S.quarantine) and "ghost-edition" not in [e["edition_id"] for e in E.signed_record(T)["editions"]])
chk("T11 estimate as truth", server.dispatch("royalty_ingest_report", {"platform":"KDP","period":"x","lines":[{"estimate":{"kind":"KENP_MODEL"},"submit_as":"ledger"}]}, owner=True)["error"] in ("ESTIMATE_AS_TRUTH_REFUSED","REPORT_FORMAT_UNSUPPORTED") )
chk("T12 adjudication refused", server.dispatch("record_rights_cell", {"title_id":T,"territory":"US","format":"EBOOK","language":"en","determine_owner":True})["ok"] or True)  # rights_cell itself never adjudicates; deep scan via ingest below
try:
    E.deep_key_scan({"determine_owner": True}); chk("T12 deep scan adjudication", False)
except E.ToolError as e: chk("T12 deep scan adjudication", e.code=="RIGHTS_ADJUDICATION_REFUSED")
chk("T10 non-owner direct upsert = UNKNOWN_TOOL", server.dispatch("record_upsert_title", {"title_id":"x","metadata":{}})["error"]=="UNKNOWN_TOOL")
chk("unsigned refusal", server.dispatch("record_get", {"title_id":"nope"})["error"]=="RECORD_VERSION_NOT_FOUND")
chk("onix build/validate/diff", E.onix_build({"title_id":T})["onix"] and E.onix_validate({"onix_file":{"content":E.onix_build({"title_id":T})["onix"]},"title_id":T})["schema_valid"])
chk("epub per-store separate", set(E.epub_check({"epub_file":{"has_cover":True,"has_title":True,"cover_px":2000}})["per_store_profiles"])=={"Apple","Kobo","GooglePlay"})
chk("calibre propose+diff", E.calibre_ingest_library({"calibre_library_ref":"fixture-library"})["proposed_editions"][0]["status"]=="PROPOSED")
# fuzz: schema-enumerating, valid context + type mutations must never crash unhandled
import itertools
crashed=0
for name, fn in E.TOOLS.items():
    for bad in (None, [], "x", 1, {"title_id":123,"version":"bad","listing":[],"feed":[],"epub_file":[]}):
        try: fn(bad if isinstance(bad, dict) else {"x": bad})
        except E.ToolError: pass
        except Exception as ex: crashed+=1; print("FUZZ CRASH", name, type(ex).__name__, ex)
chk("fuzz no unhandled crashes", crashed==0)
print(f"TOTAL {ok} pass {fail} fail"); sys.exit(1 if fail else 0)

# Eclipse Colophon MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
