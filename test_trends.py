"""Offline regression checks. Run: python -m unittest test_trends -v.

Uses an in-memory database and temporary media; never uploads real videos.
"""
import json
import logging
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autoshorts.models import TopicIdea, VideoPlan
from autoshorts.services import gemini_service, renderer, video_collector, voice_service
from backend import pipeline_runner
from backend.auth_service import create_access_token, decode_access_token
from backend.database import Base
from backend.models import User, VideoJob, YouTubeChannel
from backend.routers import jobs
from backend.scheduler import _compute_slots, _zero_view_delete_eligible, _auto_delete_zero_view_videos


class GenerationTests(unittest.TestCase):
    def test_retired_model_is_replaced_by_discovery(self):
        client = Mock()
        client.models.list.return_value = [SimpleNamespace(
            name="models/gemini-supported-flash", supported_actions=["generateContent"],
        )]
        client.models.generate_content.return_value = SimpleNamespace(text="ready")
        with patch.object(gemini_service.genai, "Client", return_value=client):
            self.assertEqual(gemini_service._generate("hello").text, "ready")
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "gemini-supported-flash")
        client.close.assert_called_once()

    def test_discovery_failure_still_tries_alias(self):
        client = Mock()
        client.models.list.side_effect = RuntimeError("discovery unavailable")
        client.models.generate_content.side_effect = [RuntimeError("404 NOT_FOUND"), SimpleNamespace(text="ready")]
        with patch.object(gemini_service.genai, "Client", return_value=client):
            self.assertEqual(gemini_service._generate("hello").text, "ready")
        self.assertEqual(client.models.generate_content.call_count, 2)

    def test_language_and_gender_choose_voice(self):
        self.assertEqual(voice_service.choose_voice("Hindi", "male"), "hi-IN-MadhurNeural")
        self.assertEqual(voice_service.choose_voice("Spanish", "female"), "es-ES-ElviraNeural")

    def test_plan_uses_preferences(self):
        payload = dict(title="History", script="A short history story.", keywords=["old castle"],
                       description="History", hashtags=["history"], voice="en-US-AriaNeural")
        with patch.object(gemini_service, "_generate", return_value=SimpleNamespace(text=json.dumps(payload))) as generate:
            plan = gemini_service.generate_video_plan("castle", niche="History", language="Urdu", gender="male")
        self.assertIn("LANGUAGE: Urdu", generate.call_args.args[0])
        self.assertIn("NICHE: History", generate.call_args.args[0])
        self.assertEqual(plan.voice, voice_service.choose_voice("Urdu", "male"))

    def test_slots_have_no_duplicate_minutes(self):
        self.assertEqual(_compute_slots("09:00", "09:01", 100), ["09:00", "09:01"])

    def test_oauth_state_is_not_a_login_token(self):
        state = create_access_token("user", purpose="oauth")
        self.assertIsNone(decode_access_token(state))
        self.assertEqual(decode_access_token(state, purpose="oauth"), "user")
        self.assertIsNone(decode_access_token(create_access_token("user"), purpose="oauth"))

    def test_captions_preserve_unicode_and_punctuation(self):
        text = "یہ آزمائش ہے — 50% isn't $5"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            chain = renderer._build_subtitle_filter(text, 2, "", caption_dir=path)
            self.assertIn("expansion=none", chain)
            captions = " ".join(p.read_text(encoding="utf-8") for p in sorted(path.glob("caption_*.txt")))
            self.assertEqual(captions, text.upper())

    def test_failed_pexels_download_uses_pixabay(self):
        def download(url, path):
            if url == "pexels":
                raise RuntimeError("bad response")
            path.write_bytes(b"video")
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            stack.enter_context(patch.object(video_collector, "search_pexels", return_value="pexels"))
            stack.enter_context(patch.object(video_collector, "search_pixabay", return_value="pixabay"))
            stack.enter_context(patch.object(video_collector, "_download_file", side_effect=download))
            self.assertEqual(len(video_collector.collect_scene_videos(["forest"], Path(folder))), 1)

    def test_real_ffmpeg_render_with_mixed_framerates(self):
        exe = renderer._find_ffmpeg()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clips = []
            for index, rate in enumerate((12, 24)):
                path = root / f"clip{index}.mp4"
                subprocess.run([exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                f"color=c=blue:s=180x320:r={rate}:d=0.6", "-c:v", "libx264", str(path)], check=True, capture_output=True)
                clips.append(path)
            audio = root / "voice.wav"
            subprocess.run([exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1.2", str(audio)], check=True, capture_output=True)
            output = root / "result.mp4"
            with patch.object(renderer, "VIDEO_WIDTH", 180), patch.object(renderer, "VIDEO_HEIGHT", 320):
                renderer.render_short("یہ آزمائش ہے. Isn't $5 50%?", audio, clips, output)
            self.assertGreater(output.stat().st_size, 1000)
            self.assertAlmostEqual(renderer._get_duration(output), 1.2, delta=0.15)


class UploadFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.user = User(email="test@example.com", name="Test", password_hash="unused", default_language="Urdu")
        self.db.add(self.user)
        self.db.flush()
        self.channel = YouTubeChannel(user_id=self.user.id, channel_id="channel", is_connected=True)
        self.db.add(self.channel)
        self.db.flush()
        self.job = VideoJob(user_id=self.user.id, channel_id=self.channel.id, status="running")
        self.db.add(self.job)
        self.db.commit()
        self.plan = VideoPlan(title="Test", hook="Hook", script="A short script", keywords=["forest"],
                              description="Test", hashtags=["shorts"], thumbnail_text="Test", category="education", voice="en-US-AriaNeural")
        self.temp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(pipeline_runner, "PROJECT_ROOT", Path(self.temp.name)))
        self.stack.enter_context(patch("backend.database.SessionLocal", self.sessions))
        self.stack.enter_context(patch("autoshorts.services.trend_sources.collect_worldwide_trends", return_value=[{"title": "Test"}]))
        self.stack.enter_context(patch.object(gemini_service, "generate_topic_ideas", return_value=[TopicIdea("New topic", "facts", "reason", "angle", 90)]))
        self.stack.enter_context(patch.object(gemini_service, "research_topic", return_value="Research"))
        self.stack.enter_context(patch.object(gemini_service, "generate_video_plan", return_value=self.plan))
        self.stack.enter_context(patch.object(voice_service, "generate_voice", side_effect=lambda **kw: kw["output_path"].write_bytes(b"audio")))
        self.stack.enter_context(patch.object(video_collector, "collect_scene_videos", return_value=[Path("clip.mp4")]))
        self.stack.enter_context(patch.object(renderer, "render_short", side_effect=lambda **kw: kw["output_path"].write_bytes(b"video")))
        self.stack.enter_context(patch("autoshorts.services.thumbnail_generator.generate_thumbnail", side_effect=lambda **kw: kw["output_path"].write_bytes(b"image")))
        self.stack.enter_context(patch.object(pipeline_runner, "_upload_to_cloudinary", return_value=""))
        self.upload = self.stack.enter_context(patch.object(pipeline_runner, "_upload_to_youtube", return_value="remote-id"))

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def run_pipeline(self):
        return pipeline_runner.run_pipeline_for_user(self.user, self.channel, self.db, self.job.id)

    def test_success_checkpoints_remote_id(self):
        result = self.run_pipeline()
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "complete")
        self.assertEqual(self.job.youtube_video_id, "remote-id")
        self.assertEqual(result["video_url"], "")

    def test_history_failure_does_not_repeat_upload(self):
        with patch.object(pipeline_runner, "_save_used_topic", side_effect=RuntimeError("db down")):
            self.assertEqual(self.run_pipeline()["youtube_video_id"], "remote-id")
        self.upload.assert_called_once()

    def test_cancel_during_cloud_storage_prevents_youtube_upload(self):
        def cancel(*args, **kwargs):
            with self.sessions() as db:
                job = db.get(VideoJob, self.job.id)
                job.status = "failed"
                job.error_message = "Cancelled by user."
                db.commit()
            return ""
        with patch.object(pipeline_runner, "_upload_to_cloudinary", side_effect=cancel):
            with self.assertRaisesRegex(RuntimeError, "Cancelled"):
                self.run_pipeline()
        self.upload.assert_not_called()

    def test_cancelled_pending_job_is_not_restarted(self):
        self.job.status = "failed"
        self.job.error_message = "Cancelled by user."
        self.db.commit()
        with patch("backend.database.engine", self.engine), patch.object(pipeline_runner, "run_pipeline_for_user") as run:
            jobs._run_pipeline_task(self.job.id, self.user.id, self.channel.id)
        run.assert_not_called()

    def test_uncertain_upload_is_not_retried(self):
        self.job.status = "pending"
        self.db.commit()
        def fail(*, db, job_id, **kwargs):
            db.query(VideoJob).filter(VideoJob.id == job_id).update({"status": "uploading"})
            db.commit()
            raise RuntimeError("connection lost")
        with patch("backend.database.engine", self.engine), patch.object(pipeline_runner, "run_pipeline_for_user", side_effect=fail) as run:
            jobs._run_pipeline_task(self.job.id, self.user.id, self.channel.id)
        run.assert_called_once()
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "failed")
        self.assertIn("Check your channel", self.job.error_message)


class ZeroViewRemovalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.user = SimpleNamespace(id="owner", is_active=True, auto_delete_zero_views=True,
                                    auto_delete_after_hours=72,
                                    auto_delete_enabled_at=self.now - timedelta(hours=100))
        self.channel = SimpleNamespace(channel_id="channel", user_id="owner", is_connected=True)
        self.job = SimpleNamespace(status="complete", youtube_video_id="video", user_id="owner",
                                   completed_at=self.now - timedelta(hours=80))
        self.stats = {"privacy": "public", "views": 0, "channel_id": "channel",
                      "published_at": (self.now - timedelta(hours=80)).isoformat()}

    def eligible(self):
        return _zero_view_delete_eligible(self.job, self.user, self.channel, self.stats, self.now)

    def test_zero_view_public_video_after_72_hours_is_eligible(self):
        self.assertTrue(self.eligible())

    def test_video_with_one_view_is_kept(self):
        self.stats["views"] = 1
        self.assertFalse(self.eligible())

    def test_unknown_counts_are_never_treated_as_zero(self):
        for views in (None, "0", False, -1):
            with self.subTest(views=views):
                self.stats["views"] = views
                self.assertFalse(self.eligible())
        self.stats.pop("views")
        self.assertFalse(self.eligible())

    def test_private_unlisted_and_unknown_privacy_are_kept(self):
        for privacy in ("private", "unlisted", ""):
            with self.subTest(privacy=privacy):
                self.stats["privacy"] = privacy
                self.assertFalse(self.eligible())

    def test_recent_upload_and_recent_publication_are_kept(self):
        self.job.completed_at = self.now - timedelta(hours=71)
        self.assertFalse(self.eligible())
        self.job.completed_at = self.now - timedelta(hours=80)
        self.stats["published_at"] = (self.now - timedelta(hours=1)).isoformat()
        self.assertFalse(self.eligible())

    def test_missing_publication_time_is_kept(self):
        self.stats.pop("published_at")
        self.assertFalse(self.eligible())

    def test_uploads_before_enabling_are_kept(self):
        self.user.auto_delete_enabled_at = self.now - timedelta(hours=1)
        self.assertFalse(self.eligible())

    def test_disabled_rule_and_disconnected_channels_are_kept(self):
        self.user.auto_delete_zero_views = False
        self.assertFalse(self.eligible())
        self.user.auto_delete_zero_views = True
        self.channel.is_connected = False
        self.assertFalse(self.eligible())

    def test_other_channels_and_users_are_kept(self):
        self.stats["channel_id"] = "someone-else"
        self.assertFalse(self.eligible())
        self.stats["channel_id"] = "channel"
        self.channel.user_id = "someone-else"
        self.assertFalse(self.eligible())

    def test_youtube_missing_statistics_stays_unknown(self):
        from backend.youtube_stats import _parse_stats
        stats = _parse_stats({"items": [{"statistics": {}, "status": {"privacyStatus": "public"}}]}, "video")
        self.assertIsNone(stats["views"])


class ZeroViewWorkerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        now = datetime.now(timezone.utc)
        self.user = User(email="removal@example.com", name="Owner", password_hash="unused",
                         auto_delete_zero_views=True, auto_delete_after_hours=72,
                         auto_delete_enabled_at=now - timedelta(hours=100))
        self.db.add(self.user)
        self.db.flush()
        self.channel = YouTubeChannel(user_id=self.user.id, channel_id="my-channel", is_connected=True)
        self.db.add(self.channel)
        self.db.flush()
        self.job = VideoJob(user_id=self.user.id, channel_id=self.channel.id, status="complete",
                            youtube_video_id="remote-id", completed_at=now - timedelta(hours=80))
        self.db.add(self.job)
        self.db.commit()
        self.job_id = self.job.id
        self.stack = ExitStack()
        self.stack.enter_context(patch("backend.database.SessionLocal", self.sessions))
        self.fetch = self.stack.enter_context(patch("backend.youtube_stats.fetch_video_stats", return_value={
            "views": 0, "privacy": "public", "channel_id": "my-channel",
            "published_at": (now - timedelta(hours=80)).isoformat(),
        }))
        self.delete = self.stack.enter_context(patch("backend.youtube_stats.delete_youtube_video", return_value=True))

    def tearDown(self):
        self.stack.close()
        self.db.close()
        self.engine.dispose()

    def test_removal_retains_audit_history_and_is_not_repeated(self):
        _auto_delete_zero_view_videos()
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "deleted")
        self.assertEqual(self.job.youtube_video_id, "remote-id")
        self.assertIsNotNone(self.job.youtube_deleted_at)
        self.assertIn("72 hours", self.job.deletion_reason)
        _auto_delete_zero_view_videos()
        self.delete.assert_called_once()

    def test_disabled_user_is_never_checked_or_deleted(self):
        self.user.auto_delete_zero_views = False
        self.db.commit()
        _auto_delete_zero_view_videos()
        self.fetch.assert_not_called()
        self.delete.assert_not_called()

    def test_old_uploads_are_not_checked_or_deleted(self):
        self.user.auto_delete_enabled_at = datetime.now(timezone.utc)
        self.db.commit()
        _auto_delete_zero_view_videos()
        self.fetch.assert_not_called()
        self.delete.assert_not_called()

    def test_stats_failure_preserves_video(self):
        self.fetch.side_effect = RuntimeError("YouTube unavailable")
        _auto_delete_zero_view_videos()
        self.delete.assert_not_called()
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "complete")

    def test_remote_failure_preserves_record_for_later_check(self):
        self.delete.return_value = False
        _auto_delete_zero_view_videos()
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "complete")
        self.assertIsNone(self.job.youtube_deleted_at)

    def test_setting_enable_records_scope_start_and_disable_stops_rule(self):
        from backend.routers.auth import update_me
        from backend.schemas import UpdateSettingsRequest
        self.user.auto_delete_zero_views = False
        self.db.commit()
        old_start = self.user.auto_delete_enabled_at
        update_me(UpdateSettingsRequest(auto_delete_zero_views=True, auto_delete_after_hours=72), self.db, self.user)
        self.assertGreater(self.user.auto_delete_enabled_at.replace(tzinfo=timezone.utc), old_start.replace(tzinfo=timezone.utc))
        update_me(UpdateSettingsRequest(auto_delete_zero_views=False), self.db, self.user)
        self.assertFalse(self.user.auto_delete_zero_views)


class YouTubeRequestTests(unittest.TestCase):
    def test_valid_token_uploads_with_bounded_metadata_and_chunk_retries(self):
        channel = SimpleNamespace(
            access_token_enc="access", refresh_token_enc="refresh",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        plan = SimpleNamespace(title="A" * 200, description="A story", hashtags=["x" * 100] * 40)
        service = Mock()
        request = service.videos.return_value.insert.return_value
        request.next_chunk.return_value = (None, {"id": "remote-id"})
        with patch("backend.auth_service.decrypt_token", side_effect=lambda text: text), \
             patch("backend.routers.channels.refresh_channel_tokens") as refresh, \
             patch("googleapiclient.discovery.build", return_value=service), \
             patch("googleapiclient.http.MediaFileUpload"):
            result = pipeline_runner._upload_to_youtube(plan, Path("video.mp4"), channel, "private", Mock(), language="Urdu")
        self.assertEqual(result, "remote-id")
        refresh.assert_not_called()
        body = service.videos.return_value.insert.call_args.kwargs["body"]
        self.assertLessEqual(len(body["snippet"]["title"]), 100)
        self.assertEqual(body["snippet"]["defaultLanguage"], "ur")
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertNotIn("madeForKids", body["status"])
        self.assertLessEqual(sum(len(t) + 3 for t in body["snippet"]["tags"]), 450)
        request.next_chunk.assert_called_once_with(num_retries=3)

    def test_expired_authorization_reports_reconnect(self):
        channel = SimpleNamespace(access_token_enc="access", refresh_token_enc="refresh",
                                  token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        with patch("backend.auth_service.decrypt_token", side_effect=lambda text: text), \
             patch("backend.routers.channels.refresh_channel_tokens", side_effect=RuntimeError("invalid_grant")), \
             patch("googleapiclient.discovery.build") as build:
            with self.assertRaisesRegex(RuntimeError, "Reconnect"):
                pipeline_runner._upload_to_youtube(Mock(), Path("video.mp4"), channel, "private", Mock())
        build.assert_not_called()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
