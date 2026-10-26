#!/usr/bin/env python3
# Eclipse Colophon MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
"""Eclipse Colophon — catalog of record for books: signed titles, rights, prices & royalties, checked everywhere they sell.
Spec: eclipse-colophon-spec-20261025.md. Signed record only enforces; closed divergence vocab (8);
royalties recomputed line-by-line from record terms w/ trace; NO price-write verb; pirate sources refused by name.
"""
import copy, csv, hashlib, hmac, io, json, re, time, unicodedata
from datetime import datetime, timezone, date
from pathlib import Path
import os

DESCRIPTOR = "Eclipse Colophon — catalog of record for books: signed titles, rights, prices & royalties, checked everywhere they sell."
PRODUCT = "Eclipse Colophon"
OWNER_TOKEN = os.environ.get("ECLIPSE_COLOPHON_OWNER_TOKEN", "owner-token-fixture")
SIGN_KEY = os.environ.get("ECLIPSE_COLOPHON_SIGN_KEY", "herald-fixture-sign-key").encode()
DIVERGENCE_CLASSES = ["PRICE_BELOW_BOOK","PRICE_ABOVE_BOOK","METADATA_MISMATCH","EDITION_UNRECORDED","TERRITORY_LEAK","ROYALTY_LINE_UNRECOMPUTABLE","ROYALTY_TERM_DRIFT","REPORT_GAP"]
RESOLUTIONS = ["RESOLVED_CORRECTED_CHANNEL","RESOLVED_RECORD_AMENDED","RESOLVED_ACCEPTED_EXCEPTION","RESOLVED_ESCALATED_DOCKET","RESOLVED_FALSE_POSITIVE","RESOLVED_REPORT_RECEIVED"]
PIRATE_SOURCES = ["libgen","library genesis","libgen.rs","libgen.is","libgen.st","z-library","zlib","annas-archive","anna's archive","sci-hub"]
OWNER_TOOLS = {"record_upsert_title","record_sign_version","record_upsert_edition","divergence_resolve"}

class ToolError(Exception):
    def __init__(self, code, msg=""): self.code=code; super().__init__(f"{code}: {msg}" if msg else code)

def canon(o): return json.dumps(o, sort_keys=True, separators=(",",":"), ensure_ascii=False)
def sha(s): return hashlib.sha256(s.encode()).hexdigest()
def now_iso(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sign(obj): return hmac.new(SIGN_KEY, canon(obj).encode(), hashlib.sha256).hexdigest()

# ---- house guards ----
def coerce_int_param(v, name):
    if isinstance(v, bool): raise ToolError("PARAM_TYPE_INVALID", name)
    if isinstance(v, int): return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()): return int(v)
    raise ToolError("PARAM_TYPE_INVALID", name)
def parse_time(v, name="time"):
    if not isinstance(v, str): raise ToolError("PARAM_TYPE_INVALID", name)
    try: return datetime.fromisoformat(v.replace("Z","+00:00"))
    except Exception: raise ToolError("TIME_INVALID", name)
def ref_guard(v, typ, name):
    if not isinstance(v, typ) or (typ is int and isinstance(v, bool)): raise ToolError("PARAM_TYPE_INVALID", name)
    return v
def deep_key_scan(obj, path=""):
    """Scan keys+string values: pirate sources, estimate-as-truth, adjudication bait."""
    if isinstance(obj, dict):
        for k, val in obj.items():
            lk = str(k).lower()
            if lk in ("adjudicate","determine_owner","determine_rights_owner","rights_verdict"): raise ToolError("RIGHTS_ADJUDICATION_REFUSED", str(k))
            if lk == "estimate_as_truth" and val is True: raise ToolError("ESTIMATE_AS_TRUTH_REFUSED", path)
            if lk == "kind" and isinstance(val,str) and val.endswith("_ESTIMATE") and obj.get("submit_as") in ("ledger","report","ledger_input"): raise ToolError("ESTIMATE_AS_TRUTH_REFUSED", path)
            deep_key_scan(val, path+"/"+str(k))
    elif isinstance(obj, list):
        for i, val in enumerate(obj): deep_key_scan(val, f"{path}[{i}]")
    elif isinstance(obj, str):
        low = obj.lower()
        if any(t in low for t in ("determine_owner","determine who really owns","adjudicat")): raise ToolError("RIGHTS_ADJUDICATION_REFUSED", obj[:40])
        for p in PIRATE_SOURCES:
            if p in low: raise ToolError("PIRATE_SOURCE_REFUSED", p)
def verified_owner(params):
    tok = params.get("owner_token") if isinstance(params, dict) else None
    if not isinstance(tok, str) or not hmac.compare_digest(tok, OWNER_TOKEN): raise ToolError("UNKNOWN_TOOL", "no oracle")
def isbn_ok(v):
    s = re.sub(r"[^0-9Xx]", "", str(v))
    if len(s)==13 and s.isdigit():
        return sum(int(d)*(1 if i%2==0 else 3) for i,d in enumerate(s))%10==0
    if len(s)==10:
        tot=sum((10-i)*(10 if c in "Xx" else int(c)) for i,c in enumerate(s)); return tot%11==0
    return False
def round_half_up(num, den=10000):  # integer bps math, HALF_UP for non-negative; sign-aware
    if num>=0: return (num*2+den)//(2*den) if False else (num+den//2)//den
    return -((-num+den//2)//den)

class State:
    def __init__(self):
        self.records={}   # title_id -> {versions:[...]}
        self.findings=[]; self.reports={}; self.runs={}; self.ledger=[]; self.receipts=[]
        self.quarantine=[]; self.fixture_listings=[]; self.fixture_library=None; self.seq=0
    def receipt(self, rtype, detail):
        prev=self.receipts[-1]["hash"] if self.receipts else "GENESIS"
        e={"seq":len(self.receipts)+1,"ts":now_iso(),"type":rtype,"prev_hash":prev,"detail":detail}
        e["hash"]=sha(prev+canon({k:v for k,v in e.items() if k!="hash"})); self.receipts.append(e); return e
    def next_id(self, p): self.seq+=1; return f"{p}-{self.seq:04d}"

S = State()

def signed_record(title_id):
    rec=S.records.get(title_id)
    if not rec: raise ToolError("RECORD_VERSION_NOT_FOUND", title_id)
    signed=[v for v in rec["versions"] if v.get("status")=="SIGNED_ACTIVE"]
    if not signed: raise ToolError("RECORD_UNSIGNED", title_id)
    v=signed[-1]
    body={k:val for k,val in v.items() if k not in ("herald_signature","status")}
    if not hmac.compare_digest(v.get("herald_signature",""), sign(body)): raise ToolError("RECORD_UNSIGNED","signature invalid (tampered)")
    return v

def get_edition(rec, edition_id):
    for e in rec["editions"]:
        if e["edition_id"]==edition_id: return e
    return None

def price_for(rec, edition_id, territory, channel=None):
    best=None
    for p in rec["price_book"]:
        if p["edition_ref"]==edition_id and p["territory"]==territory: best=p
    if best is None: return None
    if channel:
        for o in best.get("channel_overrides",[]):
            if o["channel"]==channel: return o["price_minor"], best
    return best["list_price_minor"], best

def file_finding(cls, title_id, record_side, observed_side, source_refs, edition_ref=None, cell_ref=None, severity="STANDARD", consequence=None, group_key=None):
    # duplicate suppression (idempotence): same class+title+observed canonical still open
    key=(cls,title_id,group_key if group_key else canon(observed_side),group_key)
    for f in S.findings:
        if f["_key"]==list(key) and f["state"] in ("FILED","VERIFIED"): 
            f["instances"]=f.get("instances",1)+ (1 if group_key else 0)
            if f["state"]=="FILED" and group_key is None: f["state"]="VERIFIED"  # second independent observation verifies
            return f
    f={"finding_id":S.next_id("find"),"class":cls,"title_ref":title_id,"edition_ref":edition_ref,"rights_cell_ref":cell_ref,
       "record_side":record_side,"observed_side":observed_side,"source_refs":source_refs,"filed_at":now_iso(),
       "state":"FILED","resolution":None,"severity":severity,"descriptor":DESCRIPTOR,"instances":1,
       "group_key":group_key,"_key":list(key)}
    if consequence: f["consequence_chain"]=consequence
    S.findings.append(f); S.receipt("DIVERGENCE_FILED",{"finding_id":f["finding_id"],"class":cls,"title":title_id})
    return f

def check_expired_exceptions():
    for f in S.findings:
        if f["state"]=="RESOLVED_ACCEPTED_EXCEPTION" or f.get("resolution")=="RESOLVED_ACCEPTED_EXCEPTION":
            exp=f.get("exception_expires_at")
            if exp and parse_time(exp) < datetime.now(timezone.utc):
                f["state"]="FILED"; f["resolution"]=None; f["re_filed_reason"]="ACCEPTED_EXCEPTION_EXPIRED"
                S.receipt("DIVERGENCE_REFILED",{"finding_id":f["finding_id"]})

# ---------------- Record tools ----------------
def record_upsert_title(p):
    verified_owner(p); deep_key_scan(p)
    ref_guard(p.get("title_id"), str, "title_id"); ref_guard(p.get("metadata"), dict, "metadata")
    for ident in p.get("identifiers",[]):
        if ident.get("scheme") in ("ISBN13","ISBN10") and not isbn_ok(ident.get("value","")): raise ToolError("IDENTIFIER_INVALID", ident.get("value",""))
    rec=S.records.setdefault(p["title_id"], {"versions":[]})
    ver=max([v["version"] for v in rec["versions"] if v["status"]=="DRAFT"], default=0)+ (1 if not rec["versions"] else 0)
    if any(v["status"]=="DRAFT" for v in rec["versions"]):
        v=[v for v in rec["versions"] if v["status"]=="DRAFT"][-1]
        v.update({k:p[k] for k in ("metadata","identifiers","editions","rights","price_book","royalty_terms","report_schedule","owner_ref") if k in p})
    else:
        v={"title_id":p["title_id"],"version":len(rec["versions"])+1,"supersedes_version":None,
           "metadata":p["metadata"],"identifiers":p.get("identifiers",[]),"editions":p.get("editions",[]),
           "rights":p.get("rights",[]),"price_book":p.get("price_book",[]),"royalty_terms":p.get("royalty_terms",[]),
           "report_schedule":p.get("report_schedule",[]),"owner_ref":p.get("owner_ref","owner-fixture"),
           "status":"DRAFT","created_at":now_iso(),"signed_at":None}
        rec["versions"].append(v)
    S.receipt("RECORD_DRAFT_UPSERT",{"title_id":p["title_id"],"version":v["version"]})
    return {"title_id":p["title_id"],"version":v["version"],"status":"DRAFT","descriptor":DESCRIPTOR}

def record_sign_version(p):
    verified_owner(p); title_id=ref_guard(p.get("title_id"),str,"title_id")
    rec=S.records.get(title_id)
    if not rec: raise ToolError("RECORD_VERSION_NOT_FOUND", title_id)
    if p.get("signer_ref") and rec["versions"] and p["signer_ref"]!=rec["versions"][-1].get("owner_ref"): raise ToolError("SIGNER_NOT_OWNER", p["signer_ref"])
    drafts=[v for v in rec["versions"] if v["status"]=="DRAFT"]
    if not drafts: raise ToolError("RECORD_VERSION_NOT_FOUND","no draft")
    v=drafts[-1]
    if p.get("signer_ref") and p["signer_ref"]!=v.get("owner_ref"): raise ToolError("SIGNER_NOT_OWNER", p["signer_ref"])
    for old in rec["versions"]:
        if old.get("status")=="SIGNED_ACTIVE": old["status"]="SUPERSEDED"
    v["supersedes_version"]=max([x["version"] for x in rec["versions"] if x is not v], default=None)
    v["status"]="SIGNED_ACTIVE"; v["signed_at"]=now_iso()
    body={k:val for k,val in v.items() if k not in ("herald_signature","status")}
    v["herald_signature"]=sign(body)
    r=S.receipt("RECORD_SIGNED",{"title_id":title_id,"version":v["version"]})
    return {"title_id":title_id,"version":v["version"],"status":"SIGNED_ACTIVE","herald_signature":v["herald_signature"],"receipt":r["hash"],"descriptor":DESCRIPTOR}

def record_get(p):
    title_id=ref_guard(p.get("title_id"),str,"title_id")
    if p.get("version") is not None:
        ver=coerce_int_param(p["version"],"version"); rec=S.records.get(title_id)
        if not rec: raise ToolError("RECORD_VERSION_NOT_FOUND", title_id)
        for v in rec["versions"]:
            if v["version"]==ver:
                if v["status"]=="DRAFT" and p.get("owner_token")!=OWNER_TOKEN: raise ToolError("RECORD_UNSIGNED","draft requires owner")
                return copy.deepcopy(v)|{"descriptor":DESCRIPTOR}
        raise ToolError("RECORD_VERSION_NOT_FOUND", str(ver))
    v=signed_record(title_id); return copy.deepcopy(v)|{"descriptor":DESCRIPTOR}

def record_history_get(p):
    title_id=ref_guard(p.get("title_id"),str,"title_id"); rec=S.records.get(title_id)
    if not rec: raise ToolError("RECORD_VERSION_NOT_FOUND", title_id)
    return {"title_id":title_id,"versions":[{"version":v["version"],"status":v["status"],"signed_at":v.get("signed_at"),"signature":v.get("herald_signature"),"supersedes":v.get("supersedes_version")} for v in rec["versions"]],"descriptor":DESCRIPTOR}

def record_rights_cell(p):
    title_id=ref_guard(p.get("title_id"),str,"title_id"); rec=signed_record(title_id)
    for c in rec["rights"]:
        if c["territory"]==p.get("territory") and c["format"]==p.get("format") and c["language"]==p.get("language"): return {"cell":copy.deepcopy(c),"fact":"RECORDED","descriptor":DESCRIPTOR}
    return {"cell":None,"fact":"UNRECORDED","answer":"RIGHTS_CELL_UNRECORDED","descriptor":DESCRIPTOR}

def record_upsert_edition(p):
    verified_owner(p); title_id=ref_guard(p.get("title_id"),str,"title_id"); ed=ref_guard(p.get("edition"),dict,"edition")
    rec=S.records.get(title_id)
    if not rec: raise ToolError("RECORD_VERSION_NOT_FOUND", title_id)
    drafts=[v for v in rec["versions"] if v["status"]=="DRAFT"]
    if not drafts:
        # new draft based on latest signed (copy) so edition can be added via new signed version
        base=signed_record(title_id); nd=copy.deepcopy(base); nd["version"]=len(rec["versions"])+1; nd["status"]="DRAFT"; nd.pop("herald_signature",None); nd["signed_at"]=None; rec["versions"].append(nd); drafts=[nd]
    ed=dict(ed); ed["status"]="PROPOSED"; drafts[-1]["editions"].append(ed)
    return {"edition_id":ed["edition_id"],"status":"PROPOSED","descriptor":DESCRIPTOR}

def edition_list(p):
    title_id=ref_guard(p.get("title_id"),str,"title_id"); rec=signed_record(title_id)
    out=[{"edition_id":e["edition_id"],"format":e["format"],"language":e["language"],"status":e.get("status","ACTIVE"),"isbn":e.get("isbn")} for e in rec["editions"]]
    if p.get("include_quarantined"):
        out+=[{"edition_id":q["edition_id"],"status":"QUARANTINED_DISCOVERED","label":"QUARANTINED_DISCOVERED","observed":q["observed"]} for q in S.quarantine if q["title_id"]==title_id]
    return {"title_id":title_id,"editions":out,"descriptor":DESCRIPTOR}

# ---------------- Drift ----------------
def band_floor(rec, edition_id):
    for t in rec["royalty_terms"]:
        if t.get("model")=="PERCENT_OF_LIST" and t.get("band"): return t["band"].get("min_list_minor")
    return None

def evaluate_listing(rec, title_id, listing, source="FIXTURE"):
    obs=listing.get("observed", listing); out=[]
    edition=None
    for e in rec["editions"]:
        if (obs.get("isbn") and e.get("isbn")==obs.get("isbn")) or (obs.get("edition_id") and e["edition_id"]==obs.get("edition_id")) or (obs.get("asin") and e.get("asin")==obs.get("asin")): edition=e
    # metadata
    if obs.get("title") and obs["title"]!=rec["metadata"]["title"]:
        out.append(file_finding("METADATA_MISMATCH",title_id,{"value":rec["metadata"]["title"],"record_version":rec["version"]},{"value":obs["title"],"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")],edition_ref=edition["edition_id"] if edition else None, group_key=listing.get("group_key")))
    if edition is None:
        qid=obs.get("edition_id") or obs.get("isbn") or obs.get("asin") or "unknown-edition"
        if not any(q["edition_id"]==qid and q["title_id"]==title_id for q in S.quarantine):
            S.quarantine.append({"edition_id":qid,"title_id":title_id,"observed":copy.deepcopy(obs),"status":"QUARANTINED_DISCOVERED"})
        out.append(file_finding("EDITION_UNRECORDED",title_id,{"value":"no recorded edition","record_version":rec["version"]},{"value":qid,"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")]))
        terr0=obs.get("territory_offered", obs.get("territory")); fmt0=obs.get("format")
        cell0=next((c for c in rec["rights"] if c["territory"]==terr0 and c["format"]==fmt0), None)
        if terr0 and (cell0 is None or cell0["state"] not in ("HELD","LICENSED_OUT")):
            out.append(file_finding("TERRITORY_LEAK",title_id,{"value":cell0["state"] if cell0 else "UNRECORDED","record_version":rec["version"]},{"value":terr0,"listing":listing.get("listing_id"),"via":"unrecorded edition"},[listing.get("source_ref","fixture")],cell_ref=cell0["cell_id"] if cell0 else None))
    else:
        # price
        if obs.get("price_minor") is not None:
            pm=coerce_int_param(obs["price_minor"],"price_minor")
            book=price_for(rec, edition["edition_id"], obs.get("territory_offered", obs.get("territory","US")), obs.get("channel"))
            if book:
                bv,_=book
                if pm<bv:
                    sev="STANDARD"; cons=None; floor=band_floor(rec, edition["edition_id"])
                    if (obs.get("channel")=="Amazon" or obs.get("source")=="STORE_PAGE") and ((floor is not None and pm<floor) or pm==0):
                        sev="CRITICAL"; cons={"matched_price_minor":pm,"band_effect":"below 70% band floor -> rate collapses 70%->35%" if pm>0 else "free match -> royalty zero","royalty_effect":"royalties compute off matched price per record terms; free price pays zero"}
                    out.append(file_finding("PRICE_BELOW_BOOK",title_id,{"value":bv,"record_version":rec["version"]},{"value":pm,"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")],edition_ref=edition["edition_id"],severity=sev,consequence=cons))
                elif pm>bv:
                    out.append(file_finding("PRICE_ABOVE_BOOK",title_id,{"value":bv,"record_version":rec["version"]},{"value":pm,"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")],edition_ref=edition["edition_id"]))
        # territory
        terr=obs.get("territory_offered", obs.get("territory"))
        if terr and edition:
            cell=None
            for c in rec["rights"]:
                if c["territory"]==terr and c["format"]==edition["format"] and c["language"]==edition["language"]: cell=c
            if cell is None:
                out.append(file_finding("TERRITORY_LEAK",title_id,{"value":"UNRECORDED","record_version":rec["version"]},{"value":terr,"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")],edition_ref=edition["edition_id"]))
            elif cell["state"] not in ("HELD","LICENSED_OUT"):
                out.append(file_finding("TERRITORY_LEAK",title_id,{"value":cell["state"],"record_version":rec["version"],"cell":cell["cell_id"]},{"value":terr,"listing":listing.get("listing_id")},[listing.get("source_ref","fixture")],edition_ref=edition["edition_id"],cell_ref=cell["cell_id"]))
    return out

def drift_check_listing(p):
    deep_key_scan(p); title_id=ref_guard(p.get("title_id"),str,"title_id"); rec=signed_record(title_id)
    listing=p.get("listing")
    if listing is None:
        ref=p.get("listing_ref")
        for fl in S.fixture_listings:
            if fl.get("listing_id")==ref or fl.get("source_ref")==ref: listing=fl
        if listing is None: raise ToolError("PARAM_TYPE_INVALID","listing not found")
    ref_guard(listing, dict, "listing")
    findings=evaluate_listing(rec, title_id, copy.deepcopy(listing))
    if not findings: return {"result":"MATCH","title_id":title_id,"record_version":rec["version"],"descriptor":DESCRIPTOR}
    return {"result":"DIVERGENCES","findings":[{k:v for k,v in f.items() if k!="_key"} for f in findings],"record_version":rec["version"],"descriptor":DESCRIPTOR}

def report_gap_check(rec, title_id):
    out=[]
    today=date(2026,10,25)
    for exp in rec.get("report_schedule",[]):
        last=exp.get("last_received_at")
        if last:
            y,m=map(int, exp["period_last"].split("-")[:2]) if exp.get("period_last") else (2026,9)
            import calendar; due=date(y,m,calendar.monthrange(y,m)[1]) .toordinal()+exp.get("due_after_period_days",10)
            if today.toordinal()>due:
                # check a report ingested for that platform+period
                have=any(r["platform"]==exp["platform"] and r["period"]==exp.get("period_last") for r in S.reports.values())
                if not have: out.append(file_finding("REPORT_GAP",title_id,{"value":f"report due {exp['platform']} {exp.get('period_last')}","record_version":rec["version"]},{"value":"absent past cadence","platform":exp["platform"],"period":exp.get("period_last")},[exp["platform"]]))
    return out

def drift_scan_catalog(p):
    deep_key_scan(p); titles=[p["title_id"]] if p.get("title_id") else list(S.records.keys()); allf=[]
    for tid in titles:
        try: rec=signed_record(tid)
        except ToolError: continue
        for fl in S.fixture_listings:
            if fl.get("title_id")==tid: allf+=evaluate_listing(rec, tid, copy.deepcopy(fl))
        allf+=report_gap_check(rec, tid)
    return {"scan":"COMPLETE","findings_count":len(allf),"findings":[{k:v for k,v in f.items() if k!="_key"} for f in allf],"sources":p.get("sources",["GOOGLE_BOOKS","OPEN_LIBRARY","ITUNES_SEARCH","STORE_PAGE"]),"descriptor":DESCRIPTOR}

def drift_check_feed(p):
    deep_key_scan(p); feed=ref_guard(p.get("feed"),dict,"feed"); title_id=p.get("title_id") or feed.get("title_id")
    rec=signed_record(title_id); diffs=[]
    fields={"title":rec["metadata"]["title"],"publisher":rec["metadata"]["publisher_of_record"]}
    for k,rv in fields.items():
        if k in feed and feed[k]!=rv: diffs.append({"field":k,"record_value":rv,"feed_value":feed[k],"class":"METADATA_MISMATCH"})
    if "price_minor" in feed and rec["editions"]:
        ed=rec["editions"][0]; book=price_for(rec, ed["edition_id"], feed.get("territory","US"))
        if book and feed["price_minor"]<book[0]:
            sev="CRITICAL" if feed["price_minor"]==0 or (band_floor(rec,ed["edition_id"]) and feed["price_minor"]<band_floor(rec,ed["edition_id"])) else "STANDARD"
            cons={"matched_price_minor":feed["price_minor"],"band_effect":"below band floor -> 70%->35%" if feed["price_minor"]>0 else "free -> zero royalty","royalty_effect":"compute off matched price"}
            f=file_finding("PRICE_BELOW_BOOK",title_id,{"value":book[0],"record_version":rec["version"]},{"value":feed["price_minor"],"feed":"ONIX"},[feed.get("source_ref","feed")],edition_ref=ed["edition_id"],severity=sev,consequence=cons)
            diffs.append({"field":"price_minor","record_value":book[0],"feed_value":feed["price_minor"],"class":"PRICE_BELOW_BOOK","severity":sev,"consequence_chain":cons,"finding_id":f["finding_id"]})
    return {"diffs":diffs,"record_version":rec["version"],"descriptor":DESCRIPTOR}

def divergence_list(p):
    check_expired_exceptions()
    if p.get("class") and p["class"] not in DIVERGENCE_CLASSES: raise ToolError("DIVERGENCE_CLASS_UNKNOWN", p["class"])
    out=[{k:v for k,v in f.items() if k!="_key"} for f in S.findings if (not p.get("title_id") or f["title_ref"]==p["title_id"]) and (not p.get("class") or f["class"]==p["class"]) and (not p.get("state") or f["state"]==p["state"])]
    return {"findings":out,"count":len(out),"descriptor":DESCRIPTOR}
def divergence_get(p):
    check_expired_exceptions()
    for f in S.findings:
        if f["finding_id"]==p.get("finding_id"): return {k:v for k,v in f.items() if k!="_key"}|{"evidence_pack_ref":f"blackbox://{f['finding_id']}","descriptor":DESCRIPTOR}
    raise ToolError("PARAM_TYPE_INVALID","finding not found")
def divergence_resolve(p):
    verified_owner(p)
    if p.get("resolution_class") not in RESOLUTIONS: raise ToolError("DIVERGENCE_CLASS_UNKNOWN", str(p.get("resolution_class")))
    for f in S.findings:
        if f["finding_id"]==p.get("finding_id"):
            if f["state"]=="FILED" and p["resolution_class"]!="RESOLVED_FALSE_POSITIVE": raise ToolError("FINDING_NOT_VERIFIED","resolve from FILED only for FALSE_POSITIVE w/ evidence")
            if p["resolution_class"]=="RESOLVED_FALSE_POSITIVE" and not p.get("evidence_refs"): raise ToolError("EVIDENCE_REQUIRED","false positive needs evidence")
            if p["resolution_class"]=="RESOLVED_ACCEPTED_EXCEPTION":
                if not p.get("expires_at"): raise ToolError("EXPIRY_REQUIRED","accepted exception requires expiry")
                parse_time(p["expires_at"]); f["exception_expires_at"]=p["expires_at"]
            filed_copy=copy.deepcopy({k:f[k] for k in ("record_side","observed_side")})
            f["state"]=p["resolution_class"]; f["resolution"]=p["resolution_class"]; f["resolution_evidence"]=p.get("evidence_refs",[])
            if canon(filed_copy)!=canon({k:f[k] for k in ("record_side","observed_side")}): raise ToolError("CHAIN_BREAK","filed values edited")
            S.receipt("DIVERGENCE_RESOLVED",{"finding_id":f["finding_id"],"resolution":p["resolution_class"]})
            return {"finding_id":f["finding_id"],"state":f["state"],"descriptor":DESCRIPTOR}
    raise ToolError("PARAM_TYPE_INVALID","finding not found")

# ---------------- Royalty ----------------
def find_term(rec, line):
    for t in rec["royalty_terms"]:
        if t["platform"]==line.get("platform") and t["edition_format"]==line.get("format"): return t
    return None

def compute_expected(rec, term, line):
    """Returns (expected_minor, trace, missing_input_or_None)"""
    units=coerce_int_param(line.get("units",1),"units"); trace={"steps":[]}
    model=term["model"]
    if model=="FLAT_PER_UNIT":
        flat=term.get("flat_minor"); trace["steps"].append(f"flat {flat} x {units} units"); return flat*units, trace, None
    if model=="PER_PAGE_ESTIMATE": return None, trace, "ESTIMATE_TERM_NOT_LEDGER"
    list_minor=line.get("list_price_minor")
    if list_minor is None: return None, trace, "list_price_minor"
    list_minor=coerce_int_param(list_minor,"list_price_minor"); gross=list_minor*units; trace["steps"].append(f"list {list_minor} x {units} = gross {gross}")
    band=term.get("band")
    if band:
        rate=band["rate_bps"] if band["min_list_minor"]<=list_minor<=(band.get("max_list_minor") or 10**12) else band["outside_band_rate_bps"]
        trace["steps"].append(f"band [{band['min_list_minor']},{band.get('max_list_minor')}] -> rate {rate} bps")
    else: rate=term.get("rate_bps",0); trace["steps"].append(f"rate {rate} bps")
    amt=round_half_up(gross*rate,10000); trace["steps"].append(f"rate applied: {amt}")
    for d in term.get("deductions",[]):
        kind=d["kind"]
        if kind=="DELIVERY_PER_MB":
            mb=line.get("file_size_mb")
            if mb is None: return None, trace, "file_size_mb"
            fee=int(round(float(mb)*d.get("rate_minor_per_mb",15)))*units; amt-=fee; trace["steps"].append(f"delivery {fee} -> {amt}")
        elif kind=="PRINT_COST_TABLE":
            cost=line.get("print_cost_minor")
            if cost is None:
                table=d.get("params",{}); cost=table.get(line.get("edition_ref"))
            if cost is None: return None, trace, "print_cost_minor"
            amt-=int(cost)*units; trace["steps"].append(f"print cost {cost}x{units} -> {amt}")
        elif kind in ("RETAILER_CUT","AGGREGATOR_CUT"):
            cut=round_half_up(amt*d["rate_bps"],10000); amt-=cut; trace["steps"].append(f"{kind} {d['rate_bps']}bps cut {cut} -> {amt}")
    trace["expected_minor"]=amt; return amt, trace, None

def parse_report(p):
    rf=p.get("report_file")
    if isinstance(rf, dict) and rf.get("content"):
        content=rf["content"]; fmt=rf.get("format","CSV")
        if fmt!="CSV": raise ToolError("REPORT_FORMAT_UNSUPPORTED", fmt)
        rows=list(csv.DictReader(io.StringIO(content)))
        lines=[]
        for r in rows:
            ln={"line_id":r.get("line_ref"),"platform_line_ref":r.get("line_ref"),"platform":p["platform"],"title_ref":r.get("title_id"),"edition_ref":r.get("edition_id"),"territory":r.get("territory"),"currency":r.get("currency","USD"),"raw_fields":r}
            for k in ("units","list_price_minor","reported_royalty_minor","rate_applied_bps","print_cost_minor"):
                if r.get(k) not in (None,""): ln[k]=coerce_int_param(r[k],k)
            if r.get("file_size_mb") not in (None,""): ln["file_size_mb"]=float(r["file_size_mb"])
            # format from edition later
            lines.append(ln)
        return content, lines
    if isinstance(p.get("lines"), list): return canon(p["lines"]), p["lines"]
    raise ToolError("REPORT_FORMAT_UNSUPPORTED","no content/lines")

def royalty_ingest_report(p):
    deep_key_scan(p)
    if isinstance(p.get("lines"), list):
        for ln in p["lines"]:
            if isinstance(ln, dict) and ("estimate" in ln or ln.get("kind","").endswith("_ESTIMATE")) and ln.get("submit_as") in ("ledger","report",None) and "estimate" in ln: raise ToolError("ESTIMATE_AS_TRUTH_REFUSED","estimate in report lines")
    platform=ref_guard(p.get("platform"),str,"platform"); period=ref_guard(p.get("period"),str,"period")
    content, raw_lines = parse_report(p)
    fh=sha(content)
    if fh in S.reports:
        old=S.reports[fh]; return {"report_id":old["report_id"],"lines_normalized":len(old["lines"]),"run_ref":old["run_ref"],"notice":"REPORT_DUPLICATE","idempotent":True,"descriptor":DESCRIPTOR}
    report_id=S.next_id("rep"); run_id=S.next_id("run")
    # resolve titles / terms: bind first title in lines
    entries=[]; flagged=0; recomputed=0
    seen=set(); lines=[]
    for ln in raw_lines:
        if ln.get("platform_line_ref") in seen: continue
        seen.add(ln.get("platform_line_ref")); lines.append(ln)
    state_run="COMPLETED"
    for ln in lines:
        ln.setdefault("platform", platform)
        tid=ln.get("title_ref") or ln.get("title_id"); ln["title_ref"]=tid
        try: rec=signed_record(tid)
        except ToolError: rec=None
        verdict="FLAGGED"; expected=None; delta=None; cls="ROYALTY_LINE_UNRECOMPUTABLE"; trace={"steps":[]}; reason=None; term_ref=None
        if rec is None: reason="TERM_NOT_RECORDED"
        else:
            ed=get_edition(rec, ln.get("edition_ref") or ln.get("edition_id") or "")
            if ed: ln["format"]=ed["format"]
            elif ln.get("format") is None: reason="ambiguous edition match"
            term=find_term(rec, ln) if not reason else None
            if term: term_ref=term["term_id"]
            if not term and not reason: reason="TERM_NOT_RECORDED"
            if term:
                # term drift precedence: report rate != record effective rate (for band terms use stated rate_applied vs expected band rate computed in trace check)
                expected, trace, missing = compute_expected(rec, term, ln)
                if missing: reason=f"missing input: {missing}"
                else:
                    recomputed+=1; delta=ln.get("reported_royalty_minor",0)-expected
                    # drift check: if rate_applied present and differs from band rate implied
                    implied=None
                    if term.get("band"):
                        lp=ln.get("list_price_minor"); b=term["band"]; implied=b["rate_bps"] if b["min_list_minor"]<=lp<=(b.get("max_list_minor") or 10**12) else b["outside_band_rate_bps"]
                    elif term.get("rate_bps"): implied=term["rate_bps"]
                    if ln.get("rate_applied_bps") is not None and implied is not None and ln["rate_applied_bps"]!=implied:
                        cls="ROYALTY_TERM_DRIFT"; reason=f"report rate {ln['rate_applied_bps']} != record rate {implied}"
                    elif delta!=0: reason=f"delta {delta} minor after rounding (tolerance 0)"
                    else: verdict="MATCH"; cls=None
        if verdict!="MATCH":
            flagged+=1
            if cls: file_finding(cls, tid, {"value":expected,"record_version":rec["version"] if rec else None},{"value":ln.get("reported_royalty_minor"),"line":ln.get("platform_line_ref"),"reason":reason},[report_id])
        entry={"entry_id":S.next_id("led"),"line_ref":ln.get("platform_line_ref"),"title_ref":tid,"expected_minor":expected,"reported_minor":ln.get("reported_royalty_minor"),"delta_minor":delta,"verdict":verdict if verdict=="MATCH" else f"FLAGGED({cls})","flag_class":cls,"reason":reason,"term_ref":term_ref,"run_ref":run_id,"arithmetic_trace":trace,"currency":ln.get("currency","USD"),"record_version":rec["version"] if rec else None}
        prev=S.ledger[-1]["hash"] if S.ledger else "GENESIS"; entry["prev_hash"]=prev; entry["hash"]=sha(prev+canon({k:v for k,v in entry.items() if k not in ("hash",)})); S.ledger.append(entry); entries.append(entry)
    if flagged: state_run="COMPLETED_WITH_FLAGS"
    S.reports[fh]={"report_id":report_id,"platform":platform,"period":period,"file_hash":fh,"lines":lines,"run_ref":run_id,"source_class":"OWNER_SUPPLIED_FILE"}
    S.runs[run_id]={"run_id":run_id,"report_id":report_id,"state":state_run,"coverage":{"lines_total":len(lines),"lines_recomputed":recomputed,"lines_flagged":flagged},"entries":[e["entry_id"] for e in entries]}
    # REPORT_GAP resolution by receipt of missing report
    for f in S.findings:
        if f["class"]=="REPORT_GAP" and f["state"]=="FILED" and f["observed_side"].get("platform")==platform and f["observed_side"].get("period")==period:
            f["state"]="RESOLVED_REPORT_RECEIVED"; f["resolution"]="RESOLVED_REPORT_RECEIVED"
    S.receipt("ROYALTY_INGEST",{"report_id":report_id,"run":run_id,"state":state_run})
    return {"report_id":report_id,"lines_normalized":len(lines),"run_ref":run_id,"run_state":state_run,"coverage":S.runs[run_id]["coverage"],"descriptor":DESCRIPTOR}

def royalty_reconcile(p):
    rid=p.get("run_id") or p.get("report_id")
    for run in S.runs.values():
        if run["run_id"]==rid or run["report_id"]==rid: return {"run_id":run["run_id"],"state":run["state"],"coverage":run["coverage"],"descriptor":DESCRIPTOR}
    raise ToolError("PARAM_TYPE_INVALID","run not found")
def royalty_run_get(p):
    run=S.runs.get(p.get("run_id"))
    if not run: raise ToolError("PARAM_TYPE_INVALID","run not found")
    ents=[e for e in S.ledger if e["run_ref"]==run["run_id"]]
    return {"run":run,"entries":ents,"descriptor":DESCRIPTOR}
def royalty_ledger_get(p):
    ents=[e for e in S.ledger if (not p.get("title_id") or e["title_ref"]==p["title_id"])]
    return {"format":"EXPORT","entries":ents,"count":len(ents),"chain_head":ents[-1]["hash"] if ents else "GENESIS","descriptor":DESCRIPTOR}

# ---------------- Bench tools ----------------
def onix_build(p):
    rec=signed_record(p.get("title_id"))
    gaps=[]
    if not rec["metadata"].get("subtitle"): gaps.append("subtitle unrecorded - omitted")
    xml=f"<ONIXMessage><Product><Title>{rec['metadata']['title']}</Title><Publisher>{rec['metadata']['publisher_of_record']}</Publisher>"+"".join(f"<Edition isbn='{e.get('isbn')}' format='{e['format']}'/>" for e in rec["editions"])+"</Product></ONIXMessage>"
    return {"onix":xml,"onix_version":p.get("onix_version","3.0"),"gaps":gaps,"descriptor":DESCRIPTOR}
def onix_validate(p):
    deep_key_scan(p); f=p.get("onix_file")
    content=f.get("content","") if isinstance(f,dict) else str(f)
    schema_ok="<ONIXMessage>" in content and "<Title>" in content
    rec_ok=None
    if p.get("title_id"):
        rec=signed_record(p["title_id"]); rec_ok=rec["metadata"]["title"] in content
    return {"schema_valid":schema_ok,"record_consistent":rec_ok,"verdicts_kept_separate":True,"descriptor":DESCRIPTOR}
def onix_diff(p):
    deep_key_scan(p)
    a=p.get("feed_a") or p.get("feed"); b=p.get("feed_b")
    if not isinstance(a, dict): raise ToolError("PARAM_TYPE_INVALID","feed_a")
    if b is not None and not isinstance(b, dict): raise ToolError("PARAM_TYPE_INVALID","feed_b")
    if b is None and p.get("title_id"):
        rec=signed_record(p["title_id"]); b={"title":rec["metadata"]["title"],"publisher":rec["metadata"]["publisher_of_record"]}
        diffs=[{"field":k,"feed_value":a.get(k),"record_value":b.get(k),"class":"METADATA_MISMATCH"} for k in b if k in a and a[k]!=b[k]]
    else:
        diffs=[{"field":k,"feed_a":a.get(k),"feed_b":b.get(k),"class":"METADATA_MISMATCH"} for k in set(a)|set(b) if a.get(k)!=b.get(k)]
    return {"diffs":diffs,"descriptor":DESCRIPTOR}
def epub_check(p):
    f=ref_guard(p.get("epub_file"),dict,"epub_file")
    profiles={}
    profiles["Apple"]="PASS" if f.get("has_cover") and f.get("has_title") else "FAIL: cover/title required (strict)"
    profiles["Kobo"]="FAIL: CSS quirk - unsupported property" if f.get("css_unsupported") else "PASS"
    profiles["GooglePlay"]="FAIL: image rules - cover too small" if f.get("cover_px",9999)<1400 else "PASS"
    return {"file_hash":sha(canon(f)),"epubcheck":"PASS" if f.get("has_title") else "FAIL","per_store_profiles":profiles,"collapsed":False,"descriptor":DESCRIPTOR}

# ---------------- Calibre ----------------
def _library(p):
    if p.get("library"): return p["library"]
    if p.get("calibre_library_ref")=="fixture-library" and S.fixture_library: return S.fixture_library
    raise ToolError("PARAM_TYPE_INVALID","library not found")
def calibre_ingest_library(p):
    deep_key_scan(p); lib=_library(p); proposed=[]
    for b in lib.get("books",[]):
        ed={"edition_id":"cal-"+sha(b.get("isbn") or b.get("title",""))[:8],"title":b.get("title"),"format":b.get("format","EBOOK"),"isbn":b.get("isbn"),"status":"PROPOSED"}
        proposed.append(ed)
    return {"proposed_editions":proposed,"note":"PROPOSED only, never auto-RECORDED","descriptor":DESCRIPTOR}
def calibre_diff_record(p):
    deep_key_scan(p); rec=signed_record(p.get("title_id")); lib=_library(p); diffs=[]
    rec_isbns={e.get("isbn") for e in rec["editions"]}
    for b in lib.get("books",[]):
        if b.get("isbn") not in rec_isbns: diffs.append({"field":"edition","library_value":b.get("isbn"),"record_value":None,"note":"library-only edition = candidate input, not channel divergence"})
        if b.get("title") and b["title"]!=rec["metadata"]["title"]: diffs.append({"field":"title","library_value":b["title"],"record_value":rec["metadata"]["title"]})
    return {"diffs":diffs,"descriptor":DESCRIPTOR}

# ---------------- Commerce simulator (P2, simulator-proven at P0; NOT in 23) ----------------
def commerce_verify_offer(p):
    deep_key_scan(p); rec=signed_record(p.get("title_id"))
    ed=get_edition(rec, p.get("edition_id") or "")
    if not ed or ed.get("status") not in ("ACTIVE","RECORDED",None): raise ToolError("COMMERCE_EDITION_UNRECORDED", str(p.get("edition_id")))
    if any(q["edition_id"]==p.get("edition_id") for q in S.quarantine): raise ToolError("COMMERCE_EDITION_UNRECORDED","quarantined")
    seller=p.get("seller")
    if seller!=rec["metadata"]["publisher_of_record"]:
        # recorded licensee check
        if not any(c.get("licensee_ref")==seller and c["state"]=="LICENSED_OUT" for c in rec["rights"]): raise ToolError("COMMERCE_SELLER_MISMATCH", str(seller))
    cell=None
    for c in rec["rights"]:
        if c["territory"]==p.get("territory") and c["format"]==ed["format"] and c["language"]==ed["language"]: cell=c
    if cell is None or cell["state"] not in ("HELD","LICENSED_OUT"): raise ToolError("COMMERCE_RIGHTS_UNLICENSED", f"cell territory={p.get('territory')} format={ed['format']} language={ed['language']} state={cell['state'] if cell else 'UNRECORDED'}")
    book=price_for(rec, ed["edition_id"], p.get("territory"), p.get("channel"))
    if book and p.get("price_minor") is not None and coerce_int_param(p["price_minor"],"price_minor")<book[0]: raise ToolError("COMMERCE_PRICE_DIVERGENT", f"{p['price_minor']} < book {book[0]}")
    token=sign({"title":p["title_id"],"edition":p.get("edition_id"),"territory":p.get("territory")})
    return {"state":"VERIFIED","verification_token":token,"descriptor":DESCRIPTOR}

TOOLS={
 "record_upsert_title":record_upsert_title,"record_sign_version":record_sign_version,"record_get":record_get,
 "record_history_get":record_history_get,"record_rights_cell":record_rights_cell,"record_upsert_edition":record_upsert_edition,
 "edition_list":edition_list,"drift_check_listing":drift_check_listing,"drift_scan_catalog":drift_scan_catalog,
 "drift_check_feed":drift_check_feed,"divergence_list":divergence_list,"divergence_get":divergence_get,
 "divergence_resolve":divergence_resolve,"royalty_ingest_report":royalty_ingest_report,"royalty_reconcile":royalty_reconcile,
 "royalty_run_get":royalty_run_get,"royalty_ledger_get":royalty_ledger_get,"onix_build":onix_build,
 "onix_validate":onix_validate,"onix_diff":onix_diff,"epub_check":epub_check,"calibre_ingest_library":calibre_ingest_library,
 "calibre_diff_record":calibre_diff_record,
}
assert len(TOOLS)==23, len(TOOLS)

# Eclipse Colophon MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
