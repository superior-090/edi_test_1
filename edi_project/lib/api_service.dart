import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

class ApiService {
  // ─────────────────────────────────────────────
  // BASE URL CONFIGURATION
  // ─────────────────────────────────────────────
  // LOCAL DEV    → http://localhost:8000
  // RENDER CLOUD → https://proctorai-api.onrender.com  (update after deploy)
  // ANDROID EMU  → http://10.0.2.2:8000
  static const String baseUrl = "http://localhost:8000";

  // ── Render cloud URL (update after deployment) ──
  static const String cloudUrl = "https://proctorai-api.onrender.com";

  // ─────────────────────────────────────────────
  // START SESSION
  // ─────────────────────────────────────────────
  Future<void> startSession(String sessionId, String studentId,
      {String studentName = "Unknown", String examTitle = "General Exam"}) async {
    try {
      // Start on LOCAL AI server
      await http.post(
        Uri.parse("$baseUrl/session/start"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "session_id": sessionId,
          "student_id": studentId,
        }),
      );

      // Also register on CLOUD backend
      await http.post(
        Uri.parse("$cloudUrl/session/start"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "session_id": sessionId,
          "student_id": studentId,
          "student_name": studentName,
          "exam_title": examTitle,
        }),
      );
    } catch (e) {
      print("Start session error: $e");
    }
  }

  // ─────────────────────────────────────────────
  // REGISTER SIDE CAMERA (optional for later)
  // ─────────────────────────────────────────────
  Future<void> registerSideCam(String sessionId, String url) async {
    try {
      final uri = Uri.parse("$baseUrl/session/sidecam");

      await http.post(
        uri,
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "session_id": sessionId,
          "url": url,
        }),
      );
    } catch (e) {
      print("Side cam error: $e");
    }
  }

  // ─────────────────────────────────────────────
  // UPLOAD FRAME  →  POST /proctor/upload-frame
  // ─────────────────────────────────────────────
  /// Sends a camera frame to the LOCAL AI server for detection,
  /// then forwards the result to the CLOUD backend for admin dashboard.
  Future<Map<String, dynamic>> uploadFrame(
      File imageFile, String sessionId) async {
    try {
      final uri = Uri.parse(
          "$baseUrl/proctor/upload-frame?session_id=$sessionId");

      final request = http.MultipartRequest('POST', uri);

      request.files.add(
        await http.MultipartFile.fromPath('file', imageFile.path),
      );

      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 10),
      );

      final responseBody =
          await streamedResponse.stream.bytesToString();

      if (streamedResponse.statusCode == 200) {
        final decoded =
            jsonDecode(responseBody) as Map<String, dynamic>;

        final cheating = decoded["cheating"] ?? false;
        final message = decoded["message"] ?? "Clear";

        // ── Forward result to cloud backend ──
        try {
          await http.post(
            Uri.parse("$cloudUrl/proctor/update"),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({
              "session_id": sessionId,
              "cheating": cheating,
              "cheat_type": cheating ? "PHONE" : "",
              "message": message,
              "cheat_score_delta": cheating ? 10.0 : 0.0,
            }),
          );
        } catch (_) {
          // Cloud push is best-effort; don't break the student experience
        }

        return {
          "cheating": cheating,
          "message": message,
        };
      } else {
        return {
          "cheating": false,
          "message":
              "Server error (${streamedResponse.statusCode})",
        };
      }
    } on SocketException {
      return {
        "cheating": false,
        "message": "No connection to server"
      };
    } on http.ClientException {
      return {
        "cheating": false,
        "message": "Network error"
      };
    } on FormatException {
      return {
        "cheating": false,
        "message": "Invalid response"
      };
    } catch (e) {
      return {
        "cheating": false,
        "message": "Unexpected error: $e"
      };
    }
  }

  // ─────────────────────────────────────────────
  // GET ALL SESSIONS (FOR ADMIN PANEL) — from cloud
  // ─────────────────────────────────────────────
  Future<List<dynamic>> getSessions() async {
    try {
      final uri = Uri.parse("$cloudUrl/admin/sessions");

      final response = await http.get(uri);

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as List<dynamic>;
      } else {
        return [];
      }
    } catch (e) {
      print("Fetch sessions error: $e");
      return [];
    }
  }

  // ─────────────────────────────────────────────
  // GET DASHBOARD STATS — from cloud
  // ─────────────────────────────────────────────
  Future<Map<String, dynamic>> getDashboardStats() async {
    try {
      final uri = Uri.parse("$cloudUrl/admin/stats");
      final response = await http.get(uri);

      if (response.statusCode == 200) {
        return jsonDecode(response.body);
      }
      return {};
    } catch (e) {
      print("Stats error: $e");
      return {};
    }
  }

  // ─────────────────────────────────────────────
  // VIDEO STREAM URL (FOR ADMIN UI — local server)
  // ─────────────────────────────────────────────
  String getStreamUrl(String sessionId) {
    return "$baseUrl/admin/stream/$sessionId";
  }

  // ─────────────────────────────────────────────
  // WEBSOCKET URL (FOR ADMIN DASHBOARD — cloud)
  // ─────────────────────────────────────────────
  static String get adminWebSocketUrl {
    // Convert https:// → wss:// or http:// → ws://
    final wsUrl = cloudUrl
        .replaceFirst("https://", "wss://")
        .replaceFirst("http://", "ws://");
    return "$wsUrl/ws/admin";
  }

  // ─────────────────────────────────────────────
  // STUBS (extend later)
  // ─────────────────────────────────────────────
  Future<void> login(String email, String password) async {}
  Future<void> submitExam() async {}
}