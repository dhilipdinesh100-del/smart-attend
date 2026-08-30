import sys
import os
import re

sys.path.insert(0, os.path.abspath("."))
from app import app
import database

def verify_live_dashboard():
    client = app.test_client()
    
    # 1. Check with primary admin
    u = database.get_user_by_username("admin")
    print(f"Logged-in User in DB: ID={u['id']}, Full Name='{u.get('full_name')}', Username='{u['username']}'")

    # Login
    resp = client.post("/login", data={"username": "admin", "password": "adminpassword123"}, follow_redirects=True)
    if resp.status_code != 200 or b"Dashboard" not in resp.data:
        resp = client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
    
    html = resp.data.decode("utf-8")
    
    header_match = re.search(r'<div class="dashboard-header-right.*?</div>\s*</header>', html, re.DOTALL)
    if header_match:
        print("\n--- ACTUAL RENDERED TOP-RIGHT HEADER HTML ---")
        # Print representation to avoid cp1252 character map issues
        print(header_match.group(0).encode('ascii', 'xmlcharrefreplace').decode('ascii'))
        print("---------------------------------------------\n")
    else:
        print("ERROR: dashboard-header-right NOT found in HTML!")
        return False
        
    assert "👤" in html or "&#128100;" in html, "User avatar 👤 missing!"
    assert "System Administrator" in html or "Administrator" in html, "Full name missing!"
    assert "live-clock" in html or "server-clock" in html, "Live clock missing!"
    assert "Logout" in html, "Logout button missing!"
    assert 'href="/logout"' in html, "Logout link missing!"
    print("ALL LIVE DASHBOARD HEADER VERIFICATIONS PASSED 100%!")
    return True

if __name__ == "__main__":
    success = verify_live_dashboard()
    sys.exit(0 if success else 1)
