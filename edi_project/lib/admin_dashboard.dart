import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

class ApiService {
  static const String baseUrl = "https://api.proctorai.com/v1";

  // This function now returns a Map so the UI can read the "cheating" status
  Future<Map<String, dynamic>> uploadFrame(File imageFile) async {
    try {
      // In a real app, you would uncomment the lines below to send to a server:
      /*
      var request = http.MultipartRequest('POST', Uri.parse("$baseUrl/proctor/upload-frame"));
      request.files.add(await http.MultipartFile.fromPath('frame', imageFile.path));
      var response = await request.send();
      if (response.statusCode == 200) {
        var responseData = await response.stream.bytesToString();
        return jsonDecode(responseData);
      }
      */

      // MOCK RESPONSE: Simulate a 500ms network delay
      await Future.delayed(const Duration(milliseconds: 500));

      // TOGGLE THIS: Change to 'false' to test the "Safe" state
      bool simulateCheating = true;

      return {
        "cheating": simulateCheating,
        "message": simulateCheating ? "Mobile phone detected!" : "Clear"
      };
    } catch (e) {
      return {"cheating": false, "message": "Error: $e"};
    }
  }

  // Other stubs for your project
  Future<void> login(String e, String p) async {}
  Future<void> submitExam() async {}
}