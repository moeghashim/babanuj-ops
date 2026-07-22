#!/usr/bin/env python3
"""settings-sync-prod.py — push fable's strategy/intake.yaml to prod bcc so the
ops dashboard /setup page can display it, grouped. Also ensures the pending-edits
queue table exists. Edits are applied back to intake.yaml by the Chief (git is
the source of truth); this sync only publishes current values."""
import subprocess, sys, os, json
import yaml  # pyyaml via fable repo's node? no — use python yaml if present
REPO=os.path.expanduser("~/marketing"); VPS="root@<vps-host>"; KEY=os.path.expanduser("~/.ssh/babanuj_deploy")
GROUPS = [  # (group label, [key prefixes/paths])
 ("Targets & anchors", ["margin_percent","break_even_acos","target_acos","target_tacos"]),
 ("Budgets", ["monthly_budget","amazon.new_campaign_daily_budget_usd"]),
 ("Amazon — harvest", ["amazon.harvest_"]),
 ("Amazon — bidding", ["amazon.bid_","amazon.inherited_","amazon.fixed_bid_conversion_gate"]),
 ("Amazon — hygiene", ["amazon.pruning_cycle_days"]),
 ("Google", ["google."]),
 ("Meta", ["meta."]),
 ("Triggers & review", ["negative_keyword","review.","reallocation","seasonal","high_ticket"]),
 ("Approvals (read-only)", ["approval_classes"]),
]
def flatten(d, prefix=""):
    out={}
    for k,v in d.items():
        p=f"{prefix}{k}"
        if isinstance(v,dict): out.update(flatten(v,p+"."))
        else: out[p]=v
    return out
def group_of(key):
    for g,prefixes in GROUPS:
        for p in prefixes:
            if key==p or key.startswith(p): return g
    return "Other"
def main():
    data=yaml.safe_load(open(f"{REPO}/strategy/intake.yaml"))
    flat=flatten(data)
    lines=["begin;",
     """create table if not exists strategy_settings(
        key text primary key, value text, group_name text not null,
        is_set boolean not null, updated_at timestamptz not null default now());""",
     """create table if not exists strategy_setting_edits(
        id bigserial primary key, key text not null, new_value text not null,
        status text not null default 'pending', created_at timestamptz not null default now(),
        applied_at timestamptz);""",
     "delete from strategy_settings;"]
    n=0
    for k,v in sorted(flat.items()):
        if k=="version": continue
        val=json.dumps(v) if not isinstance(v,str) else v
        is_set = "false" if v=="unset" else "true"
        lines.append("insert into strategy_settings(key,value,group_name,is_set) values"
                     f"($q${k}$q$,$q${val}$q$,$q${group_of(k)}$q$,{is_set});")
        n+=1
    lines.append("commit;")
    p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes",VPS,"docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                     input="\n".join(lines),capture_output=True,text=True,timeout=60)
    if p.returncode!=0: print(p.stderr[-400:]); sys.exit(1)
    print(f"synced {n} settings")
if __name__=="__main__": main()
