import sys,io,json
sys.path.insert(0,r"D:\02_AI\Docker\Projects\n8n-literature-workflow")
from modules.paper_discovery import search
qs=[("shear_thick","Shear thickening behaviour of polyborosiloxane"),
 ("hydrolysis","Study of hydrolysis behaviour of polyborosiloxane"),
 ("kinetics","Polyborosiloxanes PBSs Synthetic Kinetics and Characterization"),
 ("structctrl","Synthesis of Structure-Controlled Polyborosiloxanes viscoelastic response molecular mass polydimethylsiloxane"),
 ("precursorMW","Correlations Between Precursor Molecular Weight and Dynamic Mechanical Properties of Polyborosiloxane"),
 ("natcomm","Supramolecular networks high shear stiffening metal ion mediated hydrogen bonding enhancement"),
 ("solvent","Solvent-Assisted Synthesis of Polyborodimethylsiloxane PBDMS Rheological Research")]
out={}
for k,q in qs:
    try:
        out[k]=[{"t":x.get("title"),"doi":x.get("doi"),"y":x.get("year"),"inlib":x.get("in_library"),"oa":x.get("is_oa")} for x in search(q,limit=4)]
    except Exception as e:
        out[k]=[{"err":str(e)}]
io.open(r"D:\02_AI\Docker\Projects\n8n-literature-workflow\workflow_data\_disc.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=1))
print("DONE")