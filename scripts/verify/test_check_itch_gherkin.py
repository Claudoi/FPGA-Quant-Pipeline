import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify.check_itch_gherkin import check_repo


CAMPAIGNS = {
    "fase1-parser-rtl": (
        "verification/testbenches/parser",
        ("SEC-FRM-04", "SEC-FRM-05", "SEC-FRM-06", "SEC-FRM-07",
         "SEC-FRM-08", "REP-02"),
    ),
    "fase3-optimizacion": (
        "verification/testbenches/phase3",
        ("P32-01", "P32-02", "CHAIN-01"),
    ),
    "fase3-uram": (
        "verification/testbenches/uram",
        ("ANX-01", "ANX-02", "CHAIN-01"),
    ),
}


class CheckItchGherkinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        manifest = {}
        for campaign, (tests, ids) in CAMPAIGNS.items():
            gherkin = f"specs/{campaign}/gherkin"
            (self.root / gherkin).mkdir(parents=True)
            (self.root / tests).mkdir(parents=True, exist_ok=True)
            (self.root / f"specs/{campaign}/spec.md").write_text(
                "\n".join(ids), encoding="utf-8")
            (self.root / f"specs/{campaign}/verify-report.md").write_text(
                "\n".join(ids), encoding="utf-8")
            scenarios = [
                (f"  Scenario: {case} — mirror" if case == "P32-02" else
                 f"  Escenario: {case} — espejo")
                for case in ids
            ]
            (self.root / gherkin / "campaign.feature").write_text(
                "#language: es\n" + "\n".join(scenarios), encoding="utf-8")
            manifest[gherkin] = tests

        parser_tests = "\n".join(
            f"async def test_{case.lower().replace('-', '_')}(): pass"
            for case in CAMPAIGNS["fase1-parser-rtl"][1]
        )
        (self.root / "verification/testbenches/parser/test_parser.py").write_text(
            parser_tests, encoding="utf-8")
        phase3_ids = CAMPAIGNS["fase3-optimizacion"][1]
        phase3_tests = [
            "def test_p32_01(): pass",
            *(f"async def test_{case.lower().replace('-', '_')}(): pass"
              for case in phase3_ids[1:]),
        ]
        (self.root / "verification/testbenches/phase3/test_chain32.py").write_text(
            "\n".join(phase3_tests), encoding="utf-8")
        (self.root / "verification/testbenches/uram/test_uram.py").write_text(
            "\n".join(
                f"async def test_{case.lower().replace('-', '_')}(): pass"
                for case in ("ANX-01", "ANX-02")
            ),
            encoding="utf-8",
        )
        (self.root / "specs/gherkin-espejos.json").write_text(
            json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_sano_pasa(self):
        self.assertEqual(check_repo(self.root), [])

    def test_detecta_id_ausente_de_spec(self):
        spec = self.root / "specs/fase1-parser-rtl/spec.md"
        spec.write_text(spec.read_text(encoding="utf-8").replace("REP-02", ""), encoding="utf-8")

        self.assertIn(
            "fase1-parser-rtl/REP-02: ausente de spec.md",
            check_repo(self.root),
        )

    def test_detecta_id_ausente_de_verify_report(self):
        report = self.root / "specs/fase3-optimizacion/verify-report.md"
        report.write_text(report.read_text(encoding="utf-8").replace("P32-02", ""), encoding="utf-8")

        self.assertIn(
            "fase3-optimizacion/P32-02: ausente de verify-report.md",
            check_repo(self.root),
        )

    def test_detecta_id_gherkin_duplicado_en_su_campana(self):
        feature = self.root / "specs/fase3-uram/gherkin/campaign.feature"
        feature.write_text(
            feature.read_text(encoding="utf-8") + "\nEscenario: CHAIN-01 — duplicado\n",
            encoding="utf-8",
        )

        self.assertIn(
            "fase3-uram/CHAIN-01: aparece 2 veces en su corpus Gherkin",
            check_repo(self.root),
        )

    def test_detecta_manifiesto_vacio(self):
        manifest = self.root / "specs/gherkin-espejos.json"
        manifest.write_text("{}", encoding="utf-8")
        self.assertIn("manifiesto vacío", check_repo(self.root))

    def test_detecta_mapping_de_campana_incoherente(self):
        manifest = self.root / "specs/gherkin-espejos.json"
        data = {
            f"specs/{campaign}/gherkin": tests
            for campaign, (tests, _ids) in CAMPAIGNS.items()
        }
        data["specs/fase1-parser-rtl/gherkin"] = "verification/testbenches/phase3"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn(
            "specs/fase1-parser-rtl/gherkin: espejo "
            "verification/testbenches/phase3, esperado verification/testbenches/parser",
            check_repo(self.root),
        )

    def test_detecta_ruta_gherkin_inexistente(self):
        manifest = self.root / "specs/gherkin-espejos.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["specs/campana-inexistente/gherkin"] = \
            "verification/testbenches/parser"
        manifest.write_text(json.dumps(data), encoding="utf-8")

        self.assertIn(
            "specs/campana-inexistente/gherkin: ruta Gherkin inexistente",
            check_repo(self.root),
        )

    def test_detecta_ruta_espejo_inexistente(self):
        gherkin = self.root / "specs/campana-extra/gherkin"
        gherkin.mkdir(parents=True)
        manifest = self.root / "specs/gherkin-espejos.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["specs/campana-extra/gherkin"] = \
            "verification/testbenches/inexistente"
        manifest.write_text(json.dumps(data), encoding="utf-8")

        self.assertIn(
            "specs/campana-extra/gherkin: ruta espejo inexistente: "
            "verification/testbenches/inexistente",
            check_repo(self.root),
        )

    def test_detecta_cero_escenarios_para_un_id(self):
        feature = self.root / "specs/fase1-parser-rtl/gherkin/campaign.feature"
        feature.write_text(
            feature.read_text(encoding="utf-8").replace("  Escenario: REP-02 — espejo", ""),
            encoding="utf-8",
        )

        self.assertIn(
            "fase1-parser-rtl/REP-02: aparece 0 veces en su corpus Gherkin",
            check_repo(self.root),
        )

    def test_ignora_id_solo_en_comentario_gherkin(self):
        feature = self.root / "specs/fase1-parser-rtl/gherkin/campaign.feature"
        feature.write_text(
            feature.read_text(encoding="utf-8").replace(
                "  Escenario: REP-02 — espejo",
                "  # Escenario: REP-02 — solo comentario",
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "fase1-parser-rtl/REP-02: aparece 0 veces en su corpus Gherkin",
            check_repo(self.root),
        )

    def test_ignora_async_test_comentado(self):
        test_path = self.root / "verification/testbenches/parser/test_parser.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "async def test_rep_02(): pass",
                "# async def test_rep_02(): pass",
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "fase1-parser-rtl/REP-02: sin test espejo explícito en "
            "verification/testbenches/parser",
            check_repo(self.root),
        )

    def test_ignora_string_que_parece_def_test(self):
        test_path = self.root / "verification/testbenches/parser/test_parser.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "async def test_rep_02(): pass",
                "'''async def test_rep_02(): pass'''",
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "fase1-parser-rtl/REP-02: sin test espejo explícito en "
            "verification/testbenches/parser",
            check_repo(self.root),
        )

    def test_no_acepta_id_embebido_en_nombre_de_test(self):
        test_path = self.root / "verification/testbenches/parser/test_parser.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "async def test_rep_02(): pass",
                "async def test_helper_rep_02(): pass",
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "fase1-parser-rtl/REP-02: sin test espejo explícito en "
            "verification/testbenches/parser",
            check_repo(self.root),
        )

    def test_detecta_ausencia_de_test_ordinario(self):
        test_path = self.root / "verification/testbenches/phase3/test_chain32.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "def test_p32_01(): pass", "def helper_p32_01(): pass"),
            encoding="utf-8",
        )

        self.assertIn(
            "fase3-optimizacion/P32-01: sin test espejo explícito en "
            "verification/testbenches/phase3",
            check_repo(self.root),
        )

    def test_comprueba_el_espejo_externo_de_chain01_uram(self):
        test_path = self.root / "verification/testbenches/phase3/test_chain32.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "async def test_chain_01(): pass", "async def test_chain_externo(): pass"),
            encoding="utf-8",
        )
        self.assertIn(
            "fase3-uram/CHAIN-01: sin test espejo explícito en "
            "verification/testbenches/phase3/test_chain32.py",
            check_repo(self.root),
        )


if __name__ == "__main__":
    unittest.main()
