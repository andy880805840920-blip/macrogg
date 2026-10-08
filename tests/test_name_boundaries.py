"""Company-name normalization must preserve economic and technical compounds."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import news_policy as np,focus_today as ft
from src.pages import home
for text in ['令人沮喪的高通膨','持續高通膨與升息','高通脹','高通胀','高通量計算','高通透性','高通過率','高通濾波器','超微細製程','超微粒子','超微型感測器']:
 assert np.english_names(text)==text,text
for text,want in [('高通公布財報','Qualcomm公布財報'),('高通與輝達','Qualcomm與NVIDIA'),('高通透露新品','Qualcomm透露新品'),('高通量產新品','Qualcomm量產新品'),('高通過去一年成長','Qualcomm過去一年成長'),('超微型號更新','AMD型號更新'),('超微公布財報','AMD公布財報'),('Qualcomm（高通）','Qualcomm'),('高通 (Qualcomm)','Qualcomm')]:
 assert np.english_names(text)==want,(text,np.english_names(text))
assert np.english_names('Qualcomm 提到高通膨')=='Qualcomm 提到高通膨'
assert np.english_names('高通膨與高通晶片')=='高通膨與Qualcomm晶片'
raw='高通膨持續，川普與高通討論半導體。'
assert ft._tidy_focus(raw)=='高通膨持續，Donald Trump與Qualcomm討論半導體。'
data={'text':'高通膨仍高。','links':[{'title':'高通膨與高通展望','link':'https://example.test'}],'topics':[{'id':'fed','label':'聯準會','text':'高通膨持續','links':[]}]}
np.display_news(data);assert data['text']=='高通膨仍高。' and data['topics'][0]['text']=='高通膨持續'
assert data['links'][0]['title']=='高通膨與Qualcomm展望' and data['links'][0]['link']=='https://example.test'
html=home._focus_strip(dict(data,text_source='model-content',layout='main',chips=[],generated='2026-10-08'))
assert '高通膨仍高' in html and 'Qualcomm膨' not in html
assert ft.FOCUS_PROMPT_VERSION!='f13-preserve-main-independent-recovery-24h'
assert ft.TOPIC_PROMPT_VERSION!='t8-all-topics-content-no-model-skip-24h'
print('PASS: high-inflation/technical compounds preserved; real companies remain English; titles, topics, cleanup, homepage and cache versions covered')
