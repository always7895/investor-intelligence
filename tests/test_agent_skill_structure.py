"""Instruction wiring checks; these do not qualify runtime or release evidence."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/serenity-public-research/SKILL.md'

class AgentSkillStructureTests(unittest.TestCase):
    def test_skill_metadata_and_references_resolve(self):
        text = SKILL.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n'))
        front = text.split('---', 2)[1]
        self.assertIn('name: serenity-public-research', front)
        description = re.search(r'^description: (.+)$', front, re.M).group(1)
        self.assertTrue(0 < len(description) <= 1024)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            path = (SKILL.parent / target).resolve()
            self.assertTrue(path.is_relative_to(ROOT))
            self.assertTrue(path.is_file(), target)
        policy = json.loads((ROOT / 'config/v213-serenity-h6b-policy.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['canonical_serenity_skill'], SKILL.relative_to(ROOT).as_posix())

    def test_full_method_remains_required_and_preserves_evidence_distinctions(self):
        text = SKILL.read_text(encoding='utf-8')
        self.assertIn('completely before producing conclusions', text)
        method = (SKILL.parent / 'references/RESEARCH_METHOD.md').read_text(encoding='utf-8')
        self.assertFalse(method.startswith('---'))  # No duplicate discoverable skill metadata.
        for marker in ('@aleabitoreddit', '@stockgodserenity', 'qualified_substitute_exists',
                       'STRUCTURAL_DISQUALIFIER', 'ARCHIVE_ONLY', 'company_capture_confidence',
                       'UNSUPPORTED', '未揭露（無可靠公開訂單數字）', '無可靠公開預估'):
            self.assertIn(marker, method)

    def test_cross_validation_extension_preserves_scope_and_independence(self):
        self.assertIn('CROSS_VALIDATION.md', SKILL.read_text(encoding='utf-8'))
        validator = (ROOT / 'scripts/ci_v213_r75_free_relay_validate.ps1').read_text(encoding='utf-8')
        self.assertIn("'skills/serenity-public-research/references/CROSS_VALIDATION.md'", validator)
        text = (SKILL.parent / 'references/CROSS_VALIDATION.md').read_text(encoding='utf-8')
        for marker in ('Existing scoring weights', 'same disclosure lineage', 'Macro coverage cannot satisfy',
                       'PRIMARY_ONLY', 'NOT_COMPARABLE', 'UNAVAILABLE', 'point-in-time',
                       'No third-party executable code installed or copied', 'HTTP 403'):
            self.assertIn(marker, text)

    def test_standalone_repository_has_safety_and_evidence_instructions(self):
        text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        for marker in ('explicit current-session authorization', 'no-Production-mutation',
                       'No second server', 'state/STATUS.md', 'pi install -l',
                       'Known P0 must be zero', 'not a completed answer'):
            self.assertIn(marker, text)

if __name__ == '__main__':
    unittest.main()
