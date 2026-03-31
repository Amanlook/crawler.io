"""Smoke test script for the API."""

import json
import httpx

API_KEY = "sk_test_smoke_test_key_for_local_dev"
BASE = "http://localhost:8000"
headers = {"Authorization": f"Bearer {API_KEY}"}

passed = 0
failed = 0


def test(label, resp, expected_status):
    global passed, failed
    status = "PASS" if resp.status_code == expected_status else "FAIL"
    if status == "PASS":
        passed += 1
    else:
        failed += 1
    print(f"[{status}] {label} — HTTP {resp.status_code} (expected {expected_status})")
    try:
        body = resp.json()
        print(f"       {json.dumps(body, default=str)[:300]}")
    except Exception:
        print(f"       {resp.text[:300]}")
    print()


# 1. Health
r = httpx.get(f"{BASE}/health")
test("Health Check", r, 200)

# 2. Root
r = httpx.get(f"{BASE}/")
test("Root", r, 200)

# 3. Creator Lookup (existing)
r = httpx.get(
    f"{BASE}/v1/creators/lookup",
    params={"platform": "instagram", "username": "johndoe"},
    headers=headers,
)
test("Creator Lookup (johndoe)", r, 200)
creator_id = r.json().get("id") if r.status_code == 200 else None

# 4. Creator by ID
if creator_id:
    r = httpx.get(f"{BASE}/v1/creators/{creator_id}", headers=headers)
    test("Creator by ID", r, 200)

# 5. Posts Search
r = httpx.get(
    f"{BASE}/v1/posts/search",
    params={"q": "travel"},
    headers=headers,
)
test("Posts Search", r, 200)

# 6. Creator Posts
if creator_id:
    r = httpx.get(
        f"{BASE}/v1/creators/{creator_id}/posts",
        headers=headers,
    )
    test("Creator Posts", r, 200)

# 7. Invalid platform (expect 422)
r = httpx.get(
    f"{BASE}/v1/creators/lookup",
    params={"platform": "facebook", "username": "test"},
    headers=headers,
)
test("Invalid Platform", r, 422)

# 8. No auth (expect 401)
r = httpx.get(
    f"{BASE}/v1/creators/lookup",
    params={"platform": "instagram", "username": "test"},
)
test("No Auth", r, 401)

print("=" * 50)
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed == 0:
    print("✅ All smoke tests passed!")
else:
    print("❌ Some smoke tests failed.")
