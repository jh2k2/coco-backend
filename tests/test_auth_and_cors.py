from __future__ import annotations


def test_dashboard_authentication_errors(client):
    response = client.get("/api/dashboard/test-user")
    assert response.status_code == 401

    response = client.get(
        "/api/dashboard/test-user", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401

    response = client.get(
        "/api/dashboard/other-user", headers={"Authorization": "Bearer dash-token"}
    )
    assert response.status_code == 403


def test_cors_allows_dashboard_origin(client):
    allowed = client.options(
        "/api/dashboard/test-user",
        headers={
            "Origin": "http://dashboard.local",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://dashboard.local"

    blocked = client.options(
        "/api/dashboard/test-user",
        headers={
            "Origin": "https://malicious.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert blocked.status_code == 400 or blocked.headers.get("access-control-allow-origin") != "https://malicious.example"


def test_readyz_includes_cors_headers(client):
    response = client.get(
        "/readyz",
        headers={"Origin": "http://dashboard.local"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://dashboard.local"

    head = client.head("/readyz", headers={"Origin": "http://dashboard.local"})
    assert head.status_code == 200
    assert head.headers.get("access-control-allow-origin") == "http://dashboard.local"
