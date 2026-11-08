import sys, unittest, urllib.error, json, copy
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import issuer_ir_feeds as feeds
import revenue_guidance_release_check as check
TODAY=date(2026,10,23)
URL="https://pr.tsmc.com/english/latest-news"
def card(day,title="TSMC Reports Third Quarter EPS of NT$29.43",identity="3346"):
    return f'<article class="node--type-news"><a href="/english/news/{identity}"><time datetime="{day}T12:00:00Z">{day}</time><h2>{title}</h2></a></article>'
class CandidateTests(unittest.TestCase):
    def read(self,body):
        return feeds.read_channel({"kind":"TSMC_NEWS_HTML","url":URL},date(2026,10,15),TODAY,lambda u:body.encode())
    def test_reference_and_older_coverage(self):
        r=self.read(card("2026-10-15")+card("2026-10-08","TSMC September Revenue Report","3343"))
        self.assertEqual((r["status"],r["complete"]),("OK",True));self.assertEqual(len(r["items"]),1)
        ch,items=check.ir_channel({"kind":"TSMC_NEWS_HTML","url":URL},"TSMC Reports Third Quarter EPS of NT$29.43","2026-10-15",TODAY,set(),lambda u:(card("2026-10-15")+card("2026-10-08")).encode())
        self.assertTrue(ch["complete"]);self.assertEqual(items,[])
    def test_reference_alone_incomplete(self):self.assertFalse(self.read(card("2026-10-15"))["complete"])
    def test_missing_exact_reference_stays_incomplete(self):
        ch,_=check.ir_channel({"kind":"TSMC_NEWS_HTML","url":URL},"Different title","2026-10-15",TODAY,set(),lambda u:(card("2026-10-15")+card("2026-10-08")).encode())
        self.assertFalse(ch["complete"])
    def test_later_guidance_change_remains_relevant(self):
        ch,items=check.ir_channel({"kind":"TSMC_NEWS_HTML","url":URL},"TSMC Reports Third Quarter EPS of NT$29.43","2026-10-15",TODAY,set(),lambda u:(card("2026-10-16","TSMC Raises Revenue Guidance","3350")+card("2026-10-15")+card("2026-10-08")).encode())
        self.assertEqual(items[0]["disposition"],"POSSIBLY_RELEVANT")
    def test_malformed_card_empty_or_wrong_host_fail(self):
        for body in ["<html/>",card("2026-10-15").replace("<time", "<x")]:self.assertEqual(self.read(body)["status"],"FAILED")
        r=feeds.read_channel({"kind":"TSMC_NEWS_HTML","url":"https://unrelated.example/latest-news"},date(2026,10,15),TODAY,lambda u:card("2026-10-15").encode())
        self.assertEqual(r["error"],"TSMC_CHANNEL_URL")
    def test_http_diagnostic_is_sanitized_and_failed(self):
        def fetch(u):raise urllib.error.HTTPError("https://private.example/?token=secret",403,"secret",{},None)
        r=feeds.read_channel({"kind":"RSS","url":"https://ir.macom.com/rss.xml"},date(2026,8,6),TODAY,fetch)
        self.assertEqual((r["status"],r["complete"],r["items"],r["error"]),("FAILED",False,[],"HTTP_403"))
        self.assertNotIn("secret",str(r))
    def test_notice_titles_stay_review_required_without_explicit_review(self):
        for title in ["MACOM to Report Fourth Quarter and Fiscal Year 2026 Financial Results on November 5, 2026","Applied Optoelectronics Announces Date of Third Quarter 2026 Financial Results Conference Call"]:
            self.assertTrue(check.is_wire_title_possibly_relevant(title))

QUERY='press_releases({"limit":-1,"sort":["-date","-publication_datetime"]})'
def archive():
    rows={"press_releases:1":{"__typename":"press_releases","name":"reference","title":"Nebius reports second quarter 2026 financial results","date":"2026-08-12"},"press_releases:2":{"__typename":"press_releases","name":"older","title":"Earlier notice","date":"2026-07-01"}}
    rows["ROOT_QUERY"]={QUERY:[{"__ref":"press_releases:1"},{"__ref":"press_releases:2"}]}
    return {"props":{"pageProps":{"__APOLLO_STATE__":rows}}}
def embed(data):return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>'
class NewsroomArchiveTests(unittest.TestCase):
    def read(self,data):return feeds.read_channel({"kind":"NEWSROOM_HTML","url":"https://group.nebius.com/newsroom"},date(2026,8,12),TODAY,lambda u:embed(data).encode())
    def test_complete_list_resolves_exact_reference_and_older(self):
        self.assertEqual((self.read(archive())["status"],self.read(archive())["complete"]),("OK",True))
    def test_missing_ref_mutated_query_duplicate_or_bad_date_fail(self):
        for mutation in ["missing","query","duplicate","date","host"]:
            d=archive();a=d["props"]["pageProps"]["__APOLLO_STATE__"]
            if mutation=="missing":del a["press_releases:2"]
            if mutation=="query":a["ROOT_QUERY"]["different"]=a["ROOT_QUERY"].pop(QUERY)
            if mutation=="duplicate":a["ROOT_QUERY"][QUERY].append({"__ref":"press_releases:1"})
            if mutation=="date":a["press_releases:2"]["date"]="yesterday"
            if mutation=="host":a["press_releases:2"]["name"]="https://evil.example"
            self.assertEqual(self.read(d)["status"],"FAILED",mutation)
    def test_reference_day_only_incomplete_and_missing_reference_not_renewed(self):
        d=archive();a=d["props"]["pageProps"]["__APOLLO_STATE__"];a["ROOT_QUERY"][QUERY]=a["ROOT_QUERY"][QUERY][:1]
        self.assertFalse(self.read(d)["complete"])
        d=archive();d["props"]["pageProps"]["__APOLLO_STATE__"]["press_releases:1"]["title"]="Different release"
        ch,_=check.ir_channel({"kind":"NEWSROOM_HTML","url":"https://group.nebius.com/newsroom"},"Nebius reports second quarter 2026 financial results","2026-08-12",TODAY,set(),lambda u:embed(d).encode())
        self.assertFalse(ch["complete"])
    def test_truncated_json_fails_and_visible_cards_keep_original_coverage(self):
        body=embed(archive()).replace('</script>', ' BROKEN</script>')
        r=feeds.read_channel({"kind":"NEWSROOM_HTML","url":"https://group.nebius.com/newsroom"},date(2026,8,12),TODAY,lambda u:body.encode())
        self.assertEqual(r["status"],"FAILED")
    def test_truncated_tsm_html_fails(self):
        r=feeds.read_channel({"kind":"TSMC_NEWS_HTML","url":URL},date(2026,10,15),TODAY,lambda u:(card("2026-10-15")+card("2026-10-08")+'<article class="node--type-news">').encode())
        self.assertEqual(r["status"],"FAILED")

if __name__=="__main__":unittest.main()
