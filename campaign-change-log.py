#!/usr/bin/env python3
"""campaign-change-log.py — detect campaign changes by diffing daily state
snapshots. Catches EVERY change (Seller Central, API, us): budget, state,
keyword bids, keyword state. Writes changes to prod bcc campaign_change_log
and keeps snapshots under ~/babanuj-ops/state-snapshots/. Run daily."""
import importlib.util, os, sys, json, glob, subprocess
from datetime import date
spec=importlib.util.spec_from_file_location("audit", os.path.expanduser("~/babanuj-ops/amazon-ads-audit.py"))
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
SNAPDIR=os.path.expanduser("~/babanuj-ops/state-snapshots"); os.makedirs(SNAPDIR, exist_ok=True)
env=a.load_env(a.ENV); post=a.make_post(a.refresh_token(env), env)
camps=a.pull(post,*a.LIST["campaigns"]); kws=a.pull(post,*a.LIST["keywords"])
state={"campaigns":{str(c["campaignId"]):{"name":c.get("name"),"state":c.get("state"),
        "budget":(c.get("budget") or {}).get("budget"),"portfolioId":str(c.get("portfolioId") or "")} for c in camps},
       "keywords":{str(k["keywordId"]):{"campaignId":str(k["campaignId"]),"text":k.get("keywordText"),
        "matchType":k.get("matchType"),"state":k.get("state"),"bid":k.get("bid")} for k in kws}}
today=date.today().isoformat(); cur=f"{SNAPDIR}/state-{today}.json"
json.dump(state,open(cur,"w"))
prevs=sorted(f for f in glob.glob(f"{SNAPDIR}/state-*.json") if f!=cur)
if not prevs:
    print("first snapshot saved; diffs start tomorrow"); sys.exit(0)
prev=json.load(open(prevs[-1])); prev_day=prevs[-1].split("state-")[1][:10]
changes=[]
def diff(kind, old, new, fields, label):
    for _id, n in new.items():
        o=old.get(_id)
        if o is None:
            changes.append((kind,_id,label(n),"created",None,json.dumps({f:n[f] for f in fields}))); continue
        for f in fields:
            if o.get(f)!=n.get(f):
                changes.append((kind,_id,label(n),f,json.dumps(o.get(f)),json.dumps(n.get(f))))
    for _id,o in old.items():
        if _id not in new: changes.append((kind,_id,label(o),"removed",json.dumps({f:o[f] for f in fields}),None))
diff("campaign",prev["campaigns"],state["campaigns"],["state","budget","portfolioId"],lambda x:x.get("name") or "")
diff("keyword",prev["keywords"],state["keywords"],["state","bid"],lambda x:f"{x.get('text')} [{x.get('matchType')}]")
lines=["begin;","""create table if not exists campaign_change_log(
  id bigserial primary key, observed_on date not null, prev_snapshot date not null,
  entity_type text not null, entity_id text not null, entity_label text,
  field text not null, old_value text, new_value text,
  created_at timestamptz not null default now());"""]
def lit(v): return "NULL" if v is None else "$q$"+str(v)+"$q$"
for kind,_id,label,f,ov,nv in changes:
    lines.append(f"insert into campaign_change_log(observed_on,prev_snapshot,entity_type,entity_id,entity_label,field,old_value,new_value) "
                 f"values('{today}','{prev_day}','{kind}',{lit(_id)},{lit(label)},{lit(f)},{lit(ov)},{lit(nv)});")
lines.append("commit;")
p=subprocess.run(["ssh","-i",os.path.expanduser("~/.ssh/babanuj_deploy"),"-o","BatchMode=yes",os.environ.get("BCC_VPS","root@<vps-host>"),
                  "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],input="\n".join(lines),capture_output=True,text=True,timeout=180)
if p.returncode!=0: print(p.stderr[-300:]); sys.exit(1)
print(f"snapshot {today} vs {prev_day}: {len(changes)} changes logged")
