from __future__ import annotations

from newsletter.adapters.base import FetchedArtifact


def test_research_job_builds_dossier_and_writer_packet(client, monkeypatch):
    sample_html = b"""
    <html>
      <head>
        <title>Jane Founder Story</title>
        <meta name="description" content="Jane founded Acme Labs in 2019 and raised a seed round in 2021.">
      </head>
      <body>
        <h1>Jane Founder Story</h1>
        <p>Jane founded Acme Labs in 2019 after struggling with onboarding bottlenecks.</p>
        <p>In 2021, Acme Labs raised a seed round to expand the team.</p>
        <blockquote>"We built the company because the old workflow was broken."</blockquote>
      </body>
    </html>
    """

    def fake_fetch_source(self, source):
        return FetchedArtifact(
            artifact_type="html",
            media_type="text/html",
            payload=sample_html,
            metadata_json={"test": True},
        )

    monkeypatch.setattr("newsletter.adapters.web.WebAdapter.fetch_source", fake_fetch_source)

    subject_response = client.post(
        "/subjects",
        json={
            "name": "Jane Founder",
            "company_name": "Acme Labs",
            "canonical_urls": ["https://example.com/jane"],
            "aliases": ["J. Founder"],
        },
    )
    assert subject_response.status_code == 200
    subject_id = subject_response.json()["id"]

    job_response = client.post("/research-jobs", json={"subject_id": subject_id})
    assert job_response.status_code == 200
    job_payload = job_response.json()
    assert job_payload["status"] == "completed"
    assert job_payload["stage"] == "completed"

    sources_response = client.get(f"/subjects/{subject_id}/sources")
    assert sources_response.status_code == 200
    sources = sources_response.json()
    assert len(sources) == 1
    assert sources[0]["status"] == "processed"

    timeline_response = client.get(f"/subjects/{subject_id}/timeline")
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert len(timeline) >= 2
    assert any("raised a seed round" in event["summary"] for event in timeline)

    dossier_response = client.get(f"/subjects/{subject_id}/dossier")
    assert dossier_response.status_code == 200
    dossier = dossier_response.json()
    assert dossier["summary"]["claim_count"] >= 2
    assert dossier["sections"]["founder_profile"]["name"] == "Jane Founder"
    assert dossier["sections"]["notable_quotes"]

    writer_response = client.post("/writer-inputs", json={"subject_id": subject_id})
    assert writer_response.status_code == 200
    writer_packet = writer_response.json()
    assert writer_packet["subject"]["name"] == "Jane Founder"
    assert writer_packet["timeline"]
    assert writer_packet["supported_claims"]


def test_failed_x_source_does_not_abort_job(client, monkeypatch):
    sample_html = b"""
    <html><head><title>Jane Founder</title></head><body>
    <p>Jane started Acme Labs in 2020.</p>
    </body></html>
    """

    def fake_fetch_source(self, source):
        return FetchedArtifact(
            artifact_type="html",
            media_type="text/html",
            payload=sample_html,
            metadata_json={},
        )

    monkeypatch.setattr("newsletter.adapters.web.WebAdapter.fetch_source", fake_fetch_source)

    subject_response = client.post(
        "/subjects",
        json={
            "name": "Jane Founder",
            "company_name": "Acme Labs",
            "canonical_urls": ["https://example.com/jane"],
            "x_handles": ["janefounder"],
        },
    )
    subject_id = subject_response.json()["id"]

    job_response = client.post("/research-jobs", json={"subject_id": subject_id})
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "completed"

    sources_response = client.get(f"/subjects/{subject_id}/sources")
    statuses = {source["platform"]: source["status"] for source in sources_response.json()}
    assert statuses["web"] == "processed"
    assert statuses["x"] == "failed"
