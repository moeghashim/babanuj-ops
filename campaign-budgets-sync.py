#!/usr/bin/env python3
"""campaign-budgets-sync.py — upsert each SP campaign's daily budget into prod
bcc campaigns.daily_budget so /campaigns can show Budget next to spend."""
import importlib.util, subprocess, os, sys
spec=importlib.util.spec_from_file_location("audit", os.path.expanduser("~/babanuj-ops/amazon-ads-audit.py"))
audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
env=audit.load_env(audit.ENV); post=audit.make_post(audit.refresh_token(env), env)
camps=audit.pull(post, *audit.LIST["campaigns"])
lines=["begin;","alter table campaigns add column if not exists daily_budget numeric(12,2);"]
n=0
for c in camps:
    b=(c.get("budget") or {}).get("budget")
    if b is None: continue
    lines.append(f"update campaigns set daily_budget={float(b):.2f} where id='amazon_sp:{c['campaignId']}';"); n+=1
lines.append("commit;")
p=subprocess.run(["ssh","-i",os.path.expanduser("~/.ssh/babanuj_deploy"),"-o","BatchMode=yes","root@<vps-host>",
                  "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],input="\n".join(lines),capture_output=True,text=True,timeout=180)
if p.returncode!=0: print(p.stderr[-300:]); sys.exit(1)
print(f"budgets synced for {n} campaigns")
