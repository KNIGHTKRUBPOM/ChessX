"""รัน unit tests สามรอบและบันทึก line/branch coverage."""

from pathlib import Path
from io import StringIO
from time import perf_counter
import json
import os
import re
import sys
import unittest

import coverage

ROOT = Path(__file__).resolve().parents[3]
RUN_LABEL = os.environ.get("CHESS_QA_RUN", "qa-2026-11-15")
if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", RUN_LABEL):
    raise ValueError("CHESS_QA_RUN must be a lowercase evidence folder name.")
EVIDENCE = ROOT / "qa-report" / "evidence" / RUN_LABEL
CORE = ("chess_rules", "draughts_rules", "hybrid_rules", "duel_rules", "game")
MODULES = (*CORE, "rooms", "models")


class RecordResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records[test.id()] = {"status": "PASS"}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records[test.id()] = {"status":"FAIL","actual":self._exc_info_to_string(err,test)}

    def addError(self, test, err):
        super().addError(test, err)
        self.records[test.id()] = {"status":"ERROR","actual":self._exc_info_to_string(err,test)}

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records[test.id()] = {"status":"SKIP","actual":reason}

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err:
            self.records[test.id()] = {"status":"FAIL","actual":self._exc_info_to_string(err,subtest)}


def summarize_coverage(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = {}
    for path, info in data["files"].items():
        name = Path(path).stem
        s = info["summary"]
        lines = s["covered_lines"],s["num_statements"]
        branches = s["covered_branches"],s["num_branches"]
        functions = info.get("functions", {})
        functions = {fn: val for fn,val in functions.items() if fn and val["summary"]["num_statements"]}
        modules[name] = {"lines":lines, "branches":branches,
                         "functions_touched":(sum(bool(v["summary"]["covered_lines"]) for v in functions.values()),len(functions))}
    core = {metric: tuple(sum(modules[name][metric][i] for name in CORE) for i in (0,1))
            for metric in ("lines","branches","functions_touched")}
    return {"core": core, "modules": modules}


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--rounds",type=int,default=3)
    args=parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    reports=[]
    success=True
    # Re-run from fresh module imports each time so definitions are included.
    for n in range(1,args.rounds+1):
        for name in list(sys.modules):
            if name == "backend" or name.startswith("backend.") or name == "test_business_rules":
                del sys.modules[name]
        started=perf_counter()
        stream=StringIO()
        tracker=coverage.Coverage(branch=True,config_file=False,data_file=str(EVIDENCE/f".unit-coverage-{n}"),
                                  include=[str(ROOT/"backend"/(name+".py")) for name in MODULES])
        tracker.start()
        try:
            import test_business_rules as cases
            suite=unittest.TestLoader().loadTestsFromModule(cases)
            result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=RecordResult).run(suite)
        finally:
            tracker.stop()
        coverage_path=EVIDENCE/f"unit-coverage-{n}.json"
        tracker.json_report(outfile=str(coverage_path))
        (EVIDENCE/f"unit-round-{n}.txt").write_text(stream.getvalue(),encoding="utf-8")
        summary={"round":n,"tests":result.testsRun,"seconds":round(perf_counter()-started,3),
                 "passed":sum(v["status"]=="PASS" for v in result.records.values()),
                 "failures":sum(v["status"]=="FAIL" for v in result.records.values()),
                 "errors":sum(v["status"]=="ERROR" for v in result.records.values()),"skipped":len(result.skipped),
                 "coverage":summarize_coverage(coverage_path), "cases":result.records}
        reports.append(summary)
        print({k:v for k,v in summary.items() if k not in ("coverage","cases")}, flush=True)
        success &= result.wasSuccessful()
    (EVIDENCE/"unit-results.json").write_text(json.dumps(reports,indent=2,ensure_ascii=False),encoding="utf-8")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

