"""KW-7 telegram decoder (stub instance)."""
KNOWN_TOKENS = {"pola": "HDR", "kato": "ZONE_A", "nipe": "ZONE_B", "sumo": "ZONE_C", "reta": "AIR_TEMP", "vodi": "READ"}
BASE = 8
def decode_line(line, setpoints):
    return {"unknown": [t for t in line.split() if t not in KNOWN_TOKENS]}
