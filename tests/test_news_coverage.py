import sys, json, pathlib, datetime as dt, unittest
from unittest.mock import patch
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft
from src.pages import home

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.cfg=yaml.safe_load((ROOT/'config/focus.yaml').read_text(encoding='utf-8'))
        self.specs=ft.topic_specs(self.cfg)
        for s in self.specs: s['search']=[]
        self.now=dt.datetime(2026,10,8,2,tzinfo=dt.timezone.utc)
        titles={'fed':'Fed officials discuss inflation and interest rates',
            'long':'US Treasury yields rise after Treasury auction',
            'funding':'SOFR rises as bank reserves fall in repo market',
            'oil':'Oil prices rise as Iran conflict threatens oil supply',
            'equity':'Wall Street stocks rise led by Nasdaq',
            'semi':'NVIDIA announces new semiconductor chips',
            'twf':'台指期夜盤上漲，外資加碼台股',
            'election':'US midterm elections shift Senate race',
            'gold':'Gold prices rise as bullion demand grows',
            'fx':'New Taiwan dollar strengthens against US dollar'}
        self.pool=[{'title':v,'link':'https://example.com/'+k,'source':'Reuters',
                    'summary':'','at':self.now.isoformat()} for k,v in titles.items()]

    def material(self,pool=None,body=None,specs=None):
        return ft.gather_topic_material(specs or self.specs,self.pool if pool is None else pool,
            global_exclude=self.cfg.get('exclude_keywords'),now=self.now,
            _fetch=lambda *a,**k:[],_body=body or (lambda u:''))





    def test_existing_fx_taiwan_and_equity_rules_remain(self):
        bad=[
            {'title':'台指期ETF配息與申購','link':'https://example.com/etf'},
            {'title':'Indian rupee rises against dollar','link':'https://example.com/inr'},
            {'title':'日股在AI與半導體股帶動下收高','link':'https://example.com/japan'},
            {'title':'NVIDIA芯片價格上升','link':'https://example.com/no-taiwan'}]
        mat=self.material(pool=bad)
        self.assertFalse(set(mat)&{'twf','fx','equity'})








if __name__=='__main__':
    unittest.main()

