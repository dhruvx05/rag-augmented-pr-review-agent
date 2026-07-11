from unittest.mock import patch, MagicMock
from tools import run_security_scan, configure_tools

@patch("requests.get")
def test_bandit_scan_detects_vulnerabilities(mock_get):
    """
    Verify run_security_scan successfully runs bandit and detects vulnerabilities
    (shell=True, pickle.loads, hardcoded password, weak random).
    """
    # Insecure python code to test
    insecure_code = """
import pickle
import subprocess
import random

def exploit(data):
    # B105: Hardcoded password
    secret = "my_admin_password_123"
    
    # B602: shell=True execution
    subprocess.call("echo " + data, shell=True)
    
    # B301: pickle deserialization
    pickle.loads(data)
    
    # B311: standard pseudo-random generator
    key = random.random()
    return key
"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = insecure_code
    mock_get.return_value = mock_resp

    # Configure tools context
    configure_tools(repo="owner/repo", token="dummy_token", pr_number=1, head_sha="sha123")

    # Run the security scan
    report = run_security_scan("exploit_test.py")

    # Verify that bandit successfully flagged each issue
    assert "exploit_test.py" in report
    assert "B105" in report  # Hardcoded password
    assert "B602" in report  # shell=True
    assert "B301" in report  # pickle.loads
    assert "B311" in report  # random
