## ne se koriste cesto, samo go koristam za da vidam kaj mene vo terminal dali e pronajdeno nekoe parce
## za da se osiguram deka stvarno vo pozadina rabote, se naogaat parcinja i od kade idat, 
#moze da e korisno samo koa ke se zgolemam na primer znaenje

from __future__ import annotations
import sys
from pathlib import Path
import yaml
from app.core.retriever import retrieve

MIN_HIT_RATE = 0.8  #definiranje na prgm min 80% od prasanjata mora da go najdat tocniot dokument, inaku se definira pad

def main() -> int:  #funkcija koja kako izle dava 0 - testot pominal i 1 ne e pominat
    slucai = yaml.safe_load(    #slucajno se vcituvaat testovi od yaml
        (Path(__file__).parent / "test_questions.yaml").read_text(encoding="utf-8"))   #path(__file__).parent e patekata na fajlot, se spojuva so test_questions.ymal, za da moze da se raboti od bilo kade
    pogodoci = 0    # broi kolku prasanja nasle uspesen/tocen izlez
    for slucaj in slucai:   # se minuva niz sekoj test slucaj sosotaven od prasanje i ocekuvan izvor
        prashanje, ocekuvano = slucaj["question"], slucaj["expected_source"] 
        parchinja = retrieve(prashanje) # se pusta prebaruvanje prevod = search = rarank
        najdeno = any(  #se proveruva dali barem edno od najdenoto parce go ima najdeno tocnio izvor, so true se oznacuva ako e pronajdeno barem edno
            ocekuvano.lower() in str(parche.get("payload", {}).get("source", "")).lower() #dali ocekuvanjeto e del od nekoj source, upis dali e pronajdeno vo upis_semestar.pdf
            or ocekuvano.lower() in str(parche.get("payload", {}).get("title", "")).lower() # ili dali istio e najden nekade vo naslovot, proverka na dvete za da imame pogolem tolerancija
            for parche in parchinja # se proveruva za sekoe pronajdeno parce
        )
        pogodoci += najdeno # se dodava 1 ako e pronajdeno ili 0 ako ne e 
        print(f"{'yes' if najdeno else 'no'}  {prashanje!r} -> "
              f"{[parche.get('payload', {}).get('source') for parche in parchinja]}")

    stapka = pogodoci / len(slucai) if slucai else 0.0  # presmetuva stapka 
    print(f"\nHit stapka: {pogodoci}/{len(slucai)} = {stapka:.0%} (мин. {MIN_HIT_RATE:.0%})")
    return 0 if stapka >= MIN_HIT_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
