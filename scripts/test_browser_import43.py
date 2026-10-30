"""Regression for the actual script-path loader which blocked Oct30 delivery."""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path

class BrowserImport43Tests(unittest.TestCase):
    def test_script_directory_loader_can_validate_the_new_source_footer(self):
        scripts=Path(__file__).resolve().parent
        code='''import sys
sys.path.insert(0,sys.argv[1])
import browser41
source={'url':'https://example.org/full','publisher':'Synthetic','title':'Source','language':'en'}
html=browser41.source_links43.html_source(source)
assert browser41.source_links43.validate(html,required=True)
print('SCRIPT_SOURCE_FOOTER_VALIDATED')
'''
        with tempfile.TemporaryDirectory() as temp:
            env=dict(os.environ,PYTHONPATH='')
            result=subprocess.run([sys.executable,'-c',code,str(scripts)],cwd=temp,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('SCRIPT_SOURCE_FOOTER_VALIDATED',result.stdout)

if __name__=='__main__':unittest.main()
