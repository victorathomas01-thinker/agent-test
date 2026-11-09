from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.resume import tailor_text, write_preview

SOURCE = """Test Applicant

Education
Computer Science

Work Experience
Support technician, 2025
Resolved hardware tickets.
Support trainee, 2024
Assisted with workstation setup.

Projects
Built a Python and PostgreSQL dashboard.

Technical Skills
Python, Git

Certifications
Sample certification
"""


class ResumeTest(unittest.TestCase):
    def test_reorders_whole_sections_without_adding_or_losing_text(self):
        job = {'title': 'Python Developer', 'description': 'PostgreSQL dashboard'}
        preview, order = tailor_text(SOURCE, job)
        self.assertEqual(order, ['Projects', 'Technical Skills', 'Work Experience'])
        self.assertEqual(Counter(line for line in SOURCE.splitlines() if line),
                         Counter(line for line in preview.splitlines() if line))
        self.assertIn('Support technician, 2025\nResolved hardware tickets.\n'
                      'Support trainee, 2024\nAssisted with workstation setup.', preview)
        self.assertLess(preview.index('Education'), preview.index('Projects'))
        self.assertTrue(preview.endswith('Certifications\nSample certification\n'))

    def test_refuses_unrecognized_structure(self):
        with self.assertRaisesRegex(ValueError, 'two recognizable'):
            tailor_text('Test Applicant\nAn unstructured resume.', {'title': '', 'description': ''})

    def test_saves_job_specific_previews_without_touching_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'master.txt'
            source.write_text(SOURCE, encoding='utf-8')
            original = source.read_bytes()
            with patch('agent.resume.ROOT', root):
                one, _ = write_preview(source, {'id': '../first', 'title': 'Python', 'description': ''})
                repeat, _ = write_preview(source, {'id': '../first', 'title': 'Python', 'description': ''})
                two, _ = write_preview(source, {'id': 'second', 'title': 'Support', 'description': ''})
            self.assertEqual(one, repeat)
            self.assertNotEqual(one, two)
            self.assertEqual(one.parent, root / 'private' / 'resumes')
            self.assertNotEqual(one.read_text(encoding='utf-8'), two.read_text(encoding='utf-8'))
            self.assertEqual(source.read_bytes(), original)
