import sys,io,json
sys.path.insert(0,r"D:\02_AI\Docker\Projects\n8n-literature-workflow")
from modules.paper_discovery import search
qs=[("BN_review","Dynamic polymeric materials based on reversible B-O bonds with dative boron-nitrogen coordination"),
 ("BN_thermoset","Enhanced B-N coordinated dynamic boronate chemistry for recyclable thermosets with elevated stability"),
 ("BN_PU_silica","Reinforcement of boron-nitrogen coordinated polyurethane elastomers with silica nanoparticles"),
 ("Ncoord_organoboron","N-Coordinated Organoboron in Polymer Synthesis and Material Science"),
 ("PBS_PU_IPN","interpenetrating polyborosiloxane polyurethane network flexible recyclable self-healing sensor"),
 ("PBS_nanosheet","nanosheets polyborosiloxane composite shorter hydrogen-bonding clusters self-healing shapeability barrier"),
 ("PBS_BN_TIM","Self-healable dual dynamic polyborosiloxane BN composites oriented thermal conduction thermal interface"),
 ("PBS_review22","Polyborosiloxanes PBS Evolution of Approaches to the Synthesis and the Prospects of Their Application"),
 ("vitrimer_subst","Tuning the Mechanical and Dynamic Properties of Elastic Vitrimers by Tailoring the Substituents of Boronic Ester"),
 ("boronic_vitrimer","Boronic Acid Esters and Anhydrates as Dynamic Cross-Links in Vitrimers"),
 ("ccs_elastomer","Mechanically Strong Chemical Recycling Supramolecular Elastomers via Boron-Based Dynamic Bonds")]
out={}
for k,q in qs:
    try:
        out[k]=[{"t":x.get("title"),"doi":x.get("doi"),"y":x.get("year"),"inlib":x.get("in_library")} for x in search(q,limit=3)]
    except Exception as e:
        out[k]=[{"err":str(e)}]
io.open(r"D:\02_AI\Docker\Projects\n8n-literature-workflow\workflow_data\_disc2.json","w",encoding="utf-8").write(json.dumps(out,ensure_ascii=False,indent=1))
print("DONE")