"""Build bilingual mappings from paired external captures of the same controller.

Usage: python tools/build_mappings.py EXTERNAL_CAPTURE_DIRECTORY
The directory must contain de/ and en/ page files plus schedules.json manifests.
Only names, constraints, and categorical translations enter the mapping files.
"""

import json
import re
import sys
from pathlib import Path

from luxtronik_mqtt.model import NUMBER, UNITS
from luxtronik_mqtt.protocol import decode

# Expand the manufacturer's abbreviated English labels; numeric instances become levels.
LABELS = {
    "outdoor temp.": "outdoortemperature",
    "outdoor temp. Ã¸": "averageoutdoortemperature",
    "DHW": "domestichotwater",
    "DHW target": "domestichotwater/target",
    "max. flow temp.": "maximumflowtemperature",
    "ASD": "defrostbrinepressureflow",
    "EVU": "electricitysupply",
    "HD": "highpressure",
    "ND": "lowpressure",
    "MOT": "motorprotection",
    "SWT": "swimmingpoolthermostat",
    "BUP - DHW pump": "domestichotwaterpump",
    "HUP": "heatingcirculationpump",
    "VBO": "fanwellbrinepump",
    "ZIP": "circulationpump",
    "ZUP": "additionalcirculationpump",
    "ZWE 2 - SST": "additionalheatgenerator/2/collectivefault",
    "SLP": "solarcirculationpump",
    "HP since": "heatpumpsince",
    "ZWE1 since": "additionalheatgenerator/1/since",
    "net-input delay": "netinputdelay",
    "SCB time": "switchingcycleblocktime",
    "CP off since": "compressoroffsince",
    "hc add-time": "heatingcontroladdtime",
    "hc less-time": "heatingcontrollesstime",
    "TDI since": "thermaldisinfectionsince",
    "blockade DHW": "blockadedomestichotwater",
    "release ZWE DHW": "releaseadditionalheatgeneratordomestichotwater",
    "operating hours VD1": "compressor/1/operatinghours",
    "impulse VD1": "compressor/1/impulses",
    "running time Ã˜ VD1": "compressor/1/averagerunningtime",
    "operating hours ZWE1": "additionalheatgenerator/1/operatinghours",
    "operating hours HP": "heatpump",
    "operat. hours heat.": "heating",
    "operating hours DHW": "domestichotwater",
    "amount PV": "photovoltaicamount",
    "Max/IO": "inputoutputboard",
    "BMS": "buildingmanagementsystem",
    "return temp. limit.": "returntemperaturelimit",
    "hysteresis DHW": "hysteresisdomestichotwater",
    "max. return increase": "maximumreturnincrease",
    "release ZWE": "releaseadditionalheatgenerator",
    "TDI target temp.": "thermaldisinfectiontargettemperature",
    "min. heat source temp.": "minimumheatsourcetemperature",
    "max. hot gas temp.": "maximumhotgastemperature",
    "Î”t - on": "temperaturedifferenceon",
    "Î”t - off": "temperaturedifferenceoff",
    "Î”t - tank max.": "temperaturedifferencetankmaximum",
    "TEE heating": "externalenergysourcetemperatureheating",
    "TEE DHW": "externalenergysourcetemperaturedomestichotwater",
    "min HS in flow max.": "minimumheatsourceinletmaximumflow",
    "hysteresis CC": "hysteresiscoolingcircuit",
    "DHW temp. max.": "domestichotwatermaximumtemperature",
    "min return targ.temp": "minimumreturntargettemperature",
    "night lowering HC": "heatingcircuit/nightlowering",
    "EVU cut-off": "electricitysupplycutoff",
    "DHW+HP max": "domestichotwaterheatpumpmaximum",
    "brine pres/flow": "brinepressureflow",
    "monitoring VD": "compressormonitoring",
    "control HC": "heatingcircuit/control",
    "pump optim. time": "pumpoptimizationtime",
    "flow VBO": "fanwellbrinepumpflow",
    "TDI message": "thermaldisinfectionmessage",
    "heat source medium HP": "heatpumpheatsourcemedium",
    "release ZWE Heat.": "releaseadditionalheatgeneratorheating",
    "DHW postheating": "domestichotwaterpostheating",
    "DHW postheat. max.": "domestichotwaterpostheatingmaximum",
    "5+2": "weekdaysandweekend",
    "days (Mo, Tu...)": "days",
}


def segment(label):
    if label in LABELS:
        return LABELS[label]
    for pattern, template in [
        (r"(?:mix circ|MC)\s*(\d+) (flow target|flow|target)", "mixingcircuit/{0}/{1}"),
        (r"mixing circuit (\d+)", "mixingcircuit/{0}"),
        (r"minimal flow MC (\d+)", "mixingcircuit/{0}/minimumflow"),
        (r"maximum flow MC (\d+)", "mixingcircuit/{0}/maximumflow"),
        (r"night lowering MC(\d+)", "mixingcircuit/{0}/nightlowering"),
        (r"control MC(\d+)", "mixingcircuit/{0}/control"),
        (r"FP\s*(\d+)", "floorheatingpump/{0}"),
        (r"MA(\d+)(?: open)?", "mixer/{0}/open"),
        (r"MZ(\d+)(?: close)?", "mixer/{0}/close"),
        (r"AO (\d+)", "analogoutput/{0}"),
        (r"analog in (\d+)", "analoginput/{0}"),
        (r"ZWE (\d+)", "additionalheatgenerator/{0}"),
        (r"DHW (\d+)", "domestichotwater/{0}"),
    ]:
        match = re.fullmatch(pattern, label)
        if match:
            return template.format(*(re.sub(r"[^a-z0-9]", "", s.lower()) for s in match.groups()))
    return re.sub(r"[^a-z0-9]", "", label.lower())


def rows(root, page):
    result = []

    def visit(el, path):
        for node in el.findall("item"):
            p = (*path, node.findtext("name", ""))
            if node.find("value") is not None:
                result.append((p, node))
            visit(node, p)

    visit(root, tuple(page))
    return result


def q(value):
    return json.dumps(value, ensure_ascii=False)


def main(source):
    navs = {lang: decode((source / lang / "navigation.xml").read_bytes()) for lang in ("de", "en")}
    pages = {
        lang: [
            (f"page{i}.xml", [n.findtext("name")])
            for i, n in enumerate(navs[lang].findall("item")[:2])
        ]
        for lang in navs
    }
    for lang in pages:
        pages[lang] += [
            (m["file"], m["path"])
            for m in json.loads((source / lang / "schedules.json").read_text("utf-8"))
            if not m["file"].endswith("-0.xml")
        ]
    output = {
        lang: [f'language = "{lang}"', f"information_label = {q(pages[lang][0][1][0])}"]
        for lang in pages
    }
    seen = set()
    for (de_file, de_page), (en_file, en_page) in zip(pages["de"], pages["en"]):
        de_rows, en_rows = [
            rows(decode((source / lang / file).read_bytes()), page)
            for lang, file, page in (("de", de_file, de_page), ("en", en_file, en_page))
        ]
        if len(de_rows) != len(en_rows):
            raise ValueError("Paired capture structures differ")
        history_count = {}
        for (dp, dn), (ep, en) in zip(de_rows, en_rows):
            if ep in seen:
                continue
            seen.add(ep)
            history = ep[1] in ("error memory", "switch offs")
            position = None
            if history:
                position = history_count.get(ep[1], 0) + 1
                history_count[ep[1]] = position
                topic = "/".join(segment(x) for x in ep[:-1]) + "/" + str(position)
                dp, ep = (*dp[:-1], "*"), (*ep[:-1], "*")
            else:
                topic = "/".join(segment(x) for x in ep)
            value = en.findtext("value", "").strip()
            kind, unit = "text", None
            if en.findtext("type") == "timer":
                kind = "timer"
            elif en.findtext("type") == "combo":
                kind = "enum"
            elif ep[1] in ("inputs", "outputs") and value in ("on", "off"):
                kind = "boolean"
            elif re.fullmatch(r"\d+:[0-5]\d:[0-5]\d", value):
                kind, unit = "duration", "s"
            else:
                match = NUMBER.fullmatch(value)
                if match and match[2] in UNITS:
                    kind, unit = "number", UNITS[match[2]]
            if ep == ("settings", "system settings", "release ZWE DHW"):
                kind, unit = "text", None
            for lang, path, _node, page in (("de", dp, dn, de_page), ("en", ep, en, en_page)):
                lines = [
                    "",
                    "[[readings]]",
                    f"topic = {q(topic)}",
                    f"page = {q(page)}",
                    f"path = {q(path)}",
                    f"type = {q(kind)}",
                ]
                if unit is not None:
                    lines.append(f"unit = {q(unit)}")
                if position:
                    lines.append(f"position = {position}")
                if kind == "enum":
                    lines.append(
                        "options = { "
                        + ", ".join(
                            q(o.get("value")) + " = " + q(o.text) for o in en.findall("option")
                        )
                        + " }"
                    )
                if kind == "text" and lang == "de":
                    translations = {"Ein": "on", "Aus": "off", "Nein": "no", "Ja": "yes"}
                    if dn.findtext("value") != value and ep[-1] not in (
                        "controller",
                        "Max/IO",
                        "Revision",
                    ):
                        translations[dn.findtext("value")] = value
                    lines.append(
                        "translations = { "
                        + ", ".join(q(k) + " = " + q(v) for k, v in translations.items())
                        + " }"
                    )
                output[lang].extend(lines)
    destination = Path(__file__).resolve().parents[1] / "src/luxtronik_mqtt/mappings"
    destination.mkdir(parents=True, exist_ok=True)
    for lang, lines in output.items():
        (destination / (lang + ".toml")).write_text(
            "# Based on paired V3.89.3 captures; topics use expanded English labels.\n"
            + "\n".join(lines)
            + "\n",
            encoding="utf-8",
        )
    print("Generated paired mappings:", len(seen))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
