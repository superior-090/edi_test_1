import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

class ApiService {
  // ─────────────────────────────────────────────
  // BASE URL CONFIGURATION
  // ─────────────────────────────────────────────
  // Android Emulator  → http://10.0.2.2:8000
  // Real Device       → http://<YOUR_LOCAL_IP>:8000  (e.g. http://192.168.1.5:8000)
  // iOS Simulator     → http://127.0.0.1:8000
  static const String baseUrl = "http://10.0.2.2:8000"; // ← change for real device

  // ─────────────────────────────────────────────
  // UPLOAD FRAME  →  POST /proctor/upload-frame
  // ─────────────────────────────────────────────
  /// Sends a camera frame to the proctoring backend.
  /// Returns: { "cheating": bool, "message": String }
  Future<Map<String, dynamic>> uploadFrame(File imageFile) async {
    try {
      final uri = Uri.parse("$baseUrl/proctor/upload-frame");

      // Build multipart request — backend expects key: "file"
      final request = http.MultipartRequest('POST', uri);
      request.files.add(
        await http.MultipartFile.fromPath('file', imageFile.path),
      );

      // Send with a reasonable timeout
      final streamedResponse = await request.send().timeout(
        const Duration(seconds: 10),
      );

      final responseBody = await streamedResponse.stream.bytesToString();

      if (streamedResponse.statusCode == 200) {
        final decoded = jsonDecode(responseBody) as Map<String, dynamic>;
        return {
          "cheating": decoded["cheating"] as bool? ?? false,
          "message":  decoded["message"]  as String? ?? "Clear",
        };
      } else {
        // Non-200 response — surface status code for easier debugging
        return {
          "cheating": false,
          "message":  "Server error (${streamedResponse.statusCode})",
        };
      }
    } on SocketException {
      return {"cheating": false, "message": "No connection to server"};
    } on http.ClientException {
      return {"cheating": false, "message": "Network error"};
    } on FormatException {
      return {"cheating": false, "message": "Invalid response from server"};
    } catch (e) {
      return {"cheating": false, "message": "Unexpected error: $e"};
    }
  }

  // ─────────────────────────────────────────────
  // AUTH STUBS  (extend when backend is ready)
  // ─────────────────────────────────────────────
  Future<void> login(String email, String password) async {}
  Future<void> submitExam() async {}
}