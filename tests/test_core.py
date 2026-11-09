import unittest
from agent.core import answer_for,evaluate

CFG={'profile':{'first_name':'Test','email':'test@example.invalid'},'verified_answers':{'work_authorized_us':True,'needs_sponsorship_now_or_future':False},'preferences':{'keywords':['help desk','software engineer'],'locations':['charlotte','remote'],'exclude_contract':True,'exclude_senior':True,'exclude_hard_gpa_over':2.79,'minimum_score':20}}
class CoreTests(unittest.TestCase):
    def test_verified_answer(self):self.assertEqual(answer_for('Are you legally authorized to work in the United States?',CFG),('Yes','work_authorized_us'))
    def test_sponsorship(self):self.assertEqual(answer_for('Will you require visa sponsorship?',CFG),('No','needs_sponsorship_now_or_future'))
    def test_unknown(self):self.assertEqual(answer_for('Do you speak French?',CFG),(None,None))
    def test_reject_contract(self):
        j={'title':'Help Desk Contractor','location':'Charlotte','description':''}
        self.assertFalse(evaluate(j,CFG)[1])
    def test_reject_senior(self):
        j={'title':'Senior Software Engineer','location':'Remote','description':''}
        self.assertFalse(evaluate(j,CFG)[1])
    def test_good_internship(self):
        j={'title':'Software Engineer Intern','location':'Charlotte','description':''}
        self.assertTrue(evaluate(j,CFG)[1])
    def test_remote_outside_preferred_region(self):
        j={'title':'Software Engineer Intern','location':'Remote Canada','description':''}
        self.assertFalse(evaluate(j,CFG)[1])
    def test_gpa(self):
        j={'title':'Software Engineer Intern','location':'Charlotte','description':'Minimum GPA 3.0 is required'}
        self.assertFalse(evaluate(j,CFG)[1])
if __name__=='__main__':unittest.main()
