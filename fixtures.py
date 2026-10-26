#!/usr/bin/env python3
# Eclipse Colophon MCP — Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
"""Synthetic P0 fixtures: 5 titles, planted divergences across all 8 classes."""
import colophon_engine as E

def isbn13(base12):
    s=str(base12); chk=(10-sum(int(d)*(1 if i%2==0 else 3) for i,d in enumerate(s))%10)%10; return s+str(chk)

def make_title(i, title, currency="USD"):
    tid=f"title-{i}"
    isb=lambda n: isbn13(f"9780000000{i}{n}")
    eds=[{"edition_id":f"{tid}-ebook","format":"EBOOK","isbn":isb(1),"asin":f"B000{i}EB","language":"en","status":"ACTIVE","production":{"file_size_mb":2.0}},
         {"edition_id":f"{tid}-print","format":"PRINT_POD","isbn":isb(2),"language":"en","status":"ACTIVE","production":{"page_count":200}},
         {"edition_id":f"{tid}-audio","format":"AUDIO","isbn":isb(3),"language":"en","status":"ACTIVE","production":{"duration_min":300}}]
    rights=[{"cell_id":f"{tid}-c1","territory":"US","format":"EBOOK","language":"en","holder_ref":"owner-fixture","state":"HELD","licensee_ref":None},
            {"cell_id":f"{tid}-c2","territory":"GB","format":"EBOOK","language":"en","holder_ref":"owner-fixture","state":"LICENSED_OUT","licensee_ref":"LicenseeUK"},
            {"cell_id":f"{tid}-c3","territory":"DE","format":"EBOOK","language":"en","holder_ref":"other","state":"NOT_HELD","licensee_ref":None},
            {"cell_id":f"{tid}-c4","territory":"US","format":"PRINT_POD","language":"en","holder_ref":"owner-fixture","state":"HELD","licensee_ref":None},
            {"cell_id":f"{tid}-c5","territory":"FR","format":"AUDIO","language":"en","holder_ref":"owner-fixture","state":"EXPIRED","licensee_ref":None}]
    prices=[{"price_id":f"{tid}-p1","edition_ref":f"{tid}-ebook","territory":"US","currency":currency,"list_price_minor":999,"channel_overrides":[{"channel":"Kobo","price_minor":899}]},
            {"price_id":f"{tid}-p2","edition_ref":f"{tid}-print","territory":"US","currency":currency,"list_price_minor":1999,"channel_overrides":[]},
            {"price_id":f"{tid}-p3","edition_ref":f"{tid}-ebook","territory":"GB","currency":"GBP","list_price_minor":799,"channel_overrides":[]}]
    terms=[{"term_id":f"{tid}-t-kdp-ebook","platform":"KDP","edition_format":"EBOOK","model":"PERCENT_OF_LIST","band":{"min_list_minor":299,"max_list_minor":1299,"rate_bps":7000,"outside_band_rate_bps":3500},"deductions":[{"kind":"DELIVERY_PER_MB","rate_minor_per_mb":15}],"currency":currency,"rounding":{"mode":"HALF_UP","per_line":True}},
           {"term_id":f"{tid}-t-kdp-print","platform":"KDP","edition_format":"PRINT_POD","model":"PERCENT_OF_LIST","band":{"min_list_minor":1000,"max_list_minor":None,"rate_bps":6000,"outside_band_rate_bps":5000},"deductions":[{"kind":"PRINT_COST_TABLE","params":{f"{tid}-print":500}}],"currency":currency,"rounding":{"mode":"HALF_UP","per_line":True}},
           {"term_id":f"{tid}-t-agg","platform":"AGGREGATOR","edition_format":"EBOOK","model":"PERCENT_OF_LIST","rate_bps":10000,"band":None,"deductions":[{"kind":"RETAILER_CUT","rate_bps":3000},{"kind":"AGGREGATOR_CUT","rate_bps":1000}],"currency":currency,"rounding":{"mode":"HALF_UP","per_line":True}},
           {"term_id":f"{tid}-t-flat","platform":"DIRECT","edition_format":"AUDIO","model":"FLAT_PER_UNIT","flat_minor":250,"band":None,"deductions":[],"currency":currency,"rounding":{"mode":"HALF_UP","per_line":True}}]
    draft={"title_id":tid,"owner_token":E.OWNER_TOKEN,"metadata":{"title":title,"subtitle":"A Synthetic Fixture","authors":[{"name":"Fixture Author","role":"author"}],"publisher_of_record":"Fixture Press","series":None,"language_primary":"en"},
           "identifiers":[{"scheme":"ISBN13","value":isb(1),"edition_ref":f"{tid}-ebook"}],"editions":eds,"rights":rights,"price_book":prices,"royalty_terms":terms,
           "report_schedule":[{"platform":"KDP","report_kind":"royalty","cadence":"MONTHLY","due_after_period_days":10,"last_received_at":"2026-08-01","period_last":"2026-09"}],"owner_ref":"owner-fixture"}
    E.record_upsert_title(draft); E.record_sign_version({"title_id":tid,"owner_token":E.OWNER_TOKEN,"signer_ref":"owner-fixture"})
    return tid

def load_all():
    titles=[]
    for i,t in enumerate(["Alpha Fixture","Bravo Fixture","Charlie Fixture","Delta Fixture","Echo Fixture"],1): titles.append(make_title(i,t,"EUR" if i==3 else "USD"))
    t1=titles[0]
    # planted listings
    E.S.fixture_listings=[
      {"listing_id":"L-below","title_id":t1,"source":"STORE_PAGE","source_ref":"store://alpha-below","group_key":None,"observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixture","price_minor":199,"territory_offered":"US","channel":"Amazon","format":"EBOOK","language":"en"}},
      {"listing_id":"L-free","title_id":t1,"source":"STORE_PAGE","source_ref":"store://alpha-free","observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixture","price_minor":0,"territory_offered":"US","channel":"Amazon","format":"EBOOK","language":"en"}},
      {"listing_id":"L-above","title_id":t1,"source":"GOOGLE_BOOKS","source_ref":"gb://alpha-above","observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixture","price_minor":1299,"territory_offered":"US","format":"EBOOK","language":"en"}},
      {"listing_id":"L-meta","title_id":t1,"source":"OPEN_LIBRARY","source_ref":"ol://alpha-wrongtitle","observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixtur WRONG","price_minor":999,"territory_offered":"US","format":"EBOOK","language":"en"}},
      {"listing_id":"L-unrec-leak","title_id":t1,"source":"STORE_PAGE","source_ref":"store://ghost","observed":{"isbn":isbn13("978999999999"),"title":"Alpha Fixture","price_minor":999,"territory_offered":"DE","format":"EBOOK","language":"en","edition_id":"ghost-edition"}},
      {"listing_id":"L-leak","title_id":t1,"source":"STORE_PAGE","source_ref":"store://de-leak","observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixture","price_minor":999,"territory_offered":"DE","format":"EBOOK","language":"en"}},
      # propagation: one wrong field x3 listings, same group value
      *[{"listing_id":f"L-prop-{n}","title_id":t1,"source":"FEED","source_ref":f"feed://prop-{n}","group_key":"prop-title","observed":{"isbn":isbn13("978000000011"),"title":"Alpha Fixtur WRONG","price_minor":999,"territory_offered":"US","format":"EBOOK","language":"en"}} for n in range(3)],
    ]
    E.S.fixture_library={"books":[{"title":"Alpha Fixture","isbn":isbn13("978000000011"),"format":"EBOOK"},{"title":"Alpha Fixture","isbn":isbn13("978888888888"),"format":"EBOOK"},{"title":"Library Only Book","isbn":isbn13("978777777777"),"format":"EBOOK"}]}
    return titles

# KDP ebook line for title-1: list 999, 1 unit, 70% = 699 (699.3->699), delivery 2MB*15=30 => 669
KDP_CSV="line_ref,title_id,edition_id,territory,units,list_price_minor,reported_royalty_minor,currency,rate_applied_bps,file_size_mb,print_cost_minor\nK1,title-1,title-1-ebook,US,1,999,669,USD,7000,2.0,\nK2,title-1,title-1-ebook,US,1,999,670,USD,7000,2.0,\nK3,title-1,title-1-ebook,US,1,999,350,USD,3500,2.0,\nK4,title-1,title-1-ebook,US,1,999,669,USD,7000,,\nK5,title-1,title-1-print,US,1,1999,700,USD,6000,,500\n"
# K5 print: 1999*60%=1199 (1199.4->1199) -500=699; reported 700 = +1c perturbation (non-rate)
