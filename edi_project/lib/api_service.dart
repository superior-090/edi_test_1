import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'api_config.dart';

class ApiException implements Exception {
  final String message;
  final int? statusCode;

  ApiException(this.message, [this.statusCode]);

  @override
  String toString() => message;
}

class QuestionImageUpload {
  const QuestionImageUpload({
    required this.bytes,
    required this.filename,
    required this.contentType,
  });

  final Uint8List bytes;
  final String filename;
  final String contentType;
}

class ApiDownload {
  const ApiDownload({
    required this.bytes,
    required this.filename,
    required this.contentType,
  });

  final Uint8List bytes;
  final String filename;
  final String contentType;
}

class ApiService {
  ApiService({this.token});

  static String get baseUrl => ApiConfig.baseUrl;

  final String? token;

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (token != null && token!.isNotEmpty) 'Authorization': 'Bearer $token',
  };

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = Uri.parse(baseUrl);
    return base.replace(
      path: '${base.path}${path.startsWith('/') ? path : '/$path'}',
      queryParameters: query,
    );
  }

  Future<Map<String, dynamic>> login({
    required String username,
    required String password,
    required String role,
    required bool rememberMe,
  }) async {
    final response = await http.post(
      _uri('/auth/login'),
      headers: _headers,
      body: jsonEncode({
        'username': username,
        'password': password,
        'role': role,
        'remember_me': rememberMe,
      }),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> health() async {
    final response = await http
        .get(_uri('/health'))
        .timeout(const Duration(seconds: 4));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> startSession({
    required String sessionId,
    int? examId,
    required String studentId,
    required String studentName,
    required String examTitle,
    required String subject,
    required String sideCameraUrl,
  }) async {
    final response = await http
        .post(
          _uri('/session/start'),
          headers: _headers,
          body: jsonEncode({
            'session_id': sessionId,
            if (examId != null) 'exam_id': examId,
            'student_id': studentId,
            'student_name': studentName,
            'exam_title': examTitle,
            'subject': subject,
            'side_camera_url': sideCameraUrl,
          }),
        )
        .timeout(const Duration(seconds: 20));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> uploadFrame(
    Uint8List imageBytes,
    String sessionId, {
    String filename = 'front-camera.jpg',
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/proctor/upload-frame', {'session_id': sessionId}),
    );
    if (token != null && token!.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.files.add(
      http.MultipartFile.fromBytes('file', imageBytes, filename: filename),
    );

    final streamed = await request.send().timeout(const Duration(seconds: 5));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 200 && streamed.statusCode < 300) {
      return jsonDecode(body) as Map<String, dynamic>;
    }
    throw ApiException(_errorMessage(body), streamed.statusCode);
  }

  Uri frameUploadUri(String sessionId) =>
      _uri('/proctor/upload-frame', {'session_id': sessionId});

  Future<List<Map<String, dynamic>>> getQuestionImages({
    int? examId,
    String? subject,
    String? examTitle,
  }) async {
    final response = await http.get(
      _uri('/session/question-images', {
        if (examId != null) 'exam_id': '$examId',
        if (subject != null) 'subject': subject,
        if (examTitle != null) 'exam_title': examTitle,
      }),
      headers: _headers,
    );
    return _decodeMapList(response);
  }

  Future<List<Map<String, dynamic>>> getExamQuestions(int examId) async {
    final response = await http.get(
      _uri('/session/questions', {'exam_id': '$examId'}),
      headers: _headers,
    );
    return _decodeMapList(response);
  }

  Future<Map<String, dynamic>> getStudentProfile() async {
    final response = await http.get(
      _uri('/student/profile'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> updateStudentProfile({
    required String fullName,
    required String prn,
    required String branch,
    required String division,
    required String semester,
    required String year,
  }) async {
    final response = await http.put(
      _uri('/student/profile'),
      headers: _headers,
      body: jsonEncode({
        'full_name': fullName,
        'prn': prn,
        'branch': branch,
        'division': division,
        'semester': semester,
        'year': year,
      }),
    );
    return _decodeMap(response);
  }

  Future<List<dynamic>> getAvailableExams() async {
    final response = await http.get(_uri('/student/exams'), headers: _headers);
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> getTeacherSummary() async {
    final response = await http.get(
      _uri('/teacher/summary'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<List<dynamic>> getTeacherSubjects({
    String? branch,
    String? division,
    String? semester,
  }) async {
    final response = await http.get(
      _uri('/teacher/subjects', {
        if (branch != null && branch.isNotEmpty) 'branch': branch,
        if (division != null && division.isNotEmpty) 'division': division,
        if (semester != null && semester.isNotEmpty) 'semester': semester,
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> createTeacherSubject(
    Map<String, dynamic> payload,
  ) async {
    final response = await http.post(
      _uri('/teacher/subjects'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> updateTeacherSubject(
    int subjectId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      _uri('/teacher/subjects/$subjectId'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> deleteTeacherSubject(int subjectId) async {
    final response = await http.delete(
      _uri('/teacher/subjects/$subjectId'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<List<dynamic>> getTeacherExams({int? subjectId}) async {
    final response = await http.get(
      _uri('/teacher/exams', {
        if (subjectId != null) 'subject_id': '$subjectId',
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> createTeacherExam(
    Map<String, dynamic> payload,
  ) async {
    final response = await http.post(
      _uri('/teacher/exams'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> updateTeacherExam(
    int examId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      _uri('/teacher/exams/$examId'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> deleteTeacherExam(int examId) async {
    final response = await http.delete(
      _uri('/teacher/exams/$examId'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<List<Map<String, dynamic>>> getTeacherQuestionImages(
    int examId,
  ) async {
    final response = await http.get(
      _uri('/teacher/exams/$examId/question-images'),
      headers: _headers,
    );
    return _decodeMapList(response);
  }

  Future<List<Map<String, dynamic>>> getTeacherQuestions(int examId) async {
    final response = await http.get(
      _uri('/teacher/exams/$examId/questions'),
      headers: _headers,
    );
    return _decodeMapList(response);
  }

  Future<Map<String, dynamic>> createTeacherQuestion(
    int examId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.post(
      _uri('/teacher/exams/$examId/questions'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> publishTeacherExam(
    int examId, {
    required bool published,
  }) async {
    final response = await http.post(
      _uri('/teacher/exams/$examId/publish', {'published': '$published'}),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> updateTeacherQuestion(
    int questionId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      _uri('/teacher/questions/$questionId'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    return _decodeMap(response);
  }

  Future<void> reorderTeacherQuestions(
    int examId,
    List<int> questionIds,
  ) async {
    final response = await http.put(
      _uri('/teacher/exams/$examId/questions/reorder'),
      headers: _headers,
      body: jsonEncode({'question_ids': questionIds}),
    );
    _decodeMapList(response);
  }

  Future<void> deleteTeacherQuestion(int questionId) async {
    final response = await http.delete(
      _uri('/teacher/questions/$questionId'),
      headers: _headers,
    );
    _decodeMap(response);
  }

  Future<Map<String, dynamic>> uploadTeacherQuestionImage({
    required int questionId,
    required QuestionImageUpload image,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/teacher/questions/$questionId/image'),
    );
    if (token != null && token!.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        image.bytes,
        filename: image.filename,
        contentType: _mediaType(image.contentType),
      ),
    );
    final streamed = await request.send().timeout(const Duration(seconds: 30));
    final body = await streamed.stream.bytesToString();
    debugPrint(
      '[API] POST /teacher/questions/$questionId/image -> '
      '${streamed.statusCode} ${body.length > 500 ? '${body.substring(0, 500)}...' : body}',
    );
    if (streamed.statusCode >= 200 && streamed.statusCode < 300) {
      return jsonDecode(body) as Map<String, dynamic>;
    }
    throw ApiException(_errorMessage(body), streamed.statusCode);
  }

  Future<List<Map<String, dynamic>>> uploadTeacherQuestionImages({
    required int examId,
    required List<QuestionImageUpload> images,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/teacher/exams/$examId/question-images'),
    );
    if (token != null && token!.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    for (final image in images) {
      request.files.add(
        http.MultipartFile.fromBytes(
          'files',
          image.bytes,
          filename: image.filename,
          contentType: _mediaType(image.contentType),
        ),
      );
    }
    final streamed = await request.send().timeout(const Duration(seconds: 30));
    final body = await streamed.stream.bytesToString();
    debugPrint(
      '[API] POST /teacher/exams/$examId/question-images -> '
      '${streamed.statusCode} ${body.length > 500 ? '${body.substring(0, 500)}...' : body}',
    );
    if (streamed.statusCode >= 200 && streamed.statusCode < 300) {
      final decoded = jsonDecode(body) as List<dynamic>;
      return decoded
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList(growable: false);
    }
    throw ApiException(_errorMessage(body), streamed.statusCode);
  }

  Future<Map<String, dynamic>> deleteTeacherQuestionImage(int imageId) async {
    final response = await http.delete(
      _uri('/teacher/question-images/$imageId'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<List<dynamic>> getTeacherStudents({
    String? branch,
    String? division,
    String? semester,
    String? search,
  }) async {
    final response = await http.get(
      _uri('/teacher/students', {
        if (branch != null && branch.isNotEmpty) 'branch': branch,
        if (division != null && division.isNotEmpty) 'division': division,
        if (semester != null && semester.isNotEmpty) 'semester': semester,
        if (search != null && search.isNotEmpty) 'search': search,
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<List<dynamic>> getTeacherResults({
    int? subjectId,
    String? branch,
    String? division,
    String? search,
  }) async {
    final response = await http.get(
      _uri('/teacher/results', {
        if (subjectId != null) 'subject_id': '$subjectId',
        if (branch != null && branch.isNotEmpty) 'branch': branch,
        if (division != null && division.isNotEmpty) 'division': division,
        if (search != null && search.isNotEmpty) 'search': search,
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<List<dynamic>> getTeacherViolations({
    int? subjectId,
    String? branch,
    String? division,
    String? search,
  }) async {
    final response = await http.get(
      _uri('/teacher/violations', {
        if (subjectId != null) 'subject_id': '$subjectId',
        if (branch != null && branch.isNotEmpty) 'branch': branch,
        if (division != null && division.isNotEmpty) 'division': division,
        if (search != null && search.isNotEmpty) 'search': search,
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<ApiDownload> downloadTeacherResultsExport({
    required String format,
    int? subjectId,
    String? branch,
    String? division,
    String? search,
  }) async {
    final response = await http.get(
      _uri('/teacher/results/export', {
        'format': format,
        if (subjectId != null) 'subject_id': '$subjectId',
        if (branch != null && branch.isNotEmpty) 'branch': branch,
        if (division != null && division.isNotEmpty) 'division': division,
        if (search != null && search.isNotEmpty) 'search': search,
      }),
      headers: _headers,
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(_errorMessage(response.body), response.statusCode);
    }
    final extension = format == 'excel' ? 'xls' : 'csv';
    return ApiDownload(
      bytes: response.bodyBytes,
      filename: 'exam-results.$extension',
      contentType: response.headers['content-type'] ?? 'text/csv',
    );
  }

  Future<List<dynamic>> getAdminQuestionImages({
    String? subject,
    String? examTitle,
  }) async {
    final response = await http.get(
      _uri('/admin/question-images', {
        if (subject != null && subject != 'ALL') 'subject': subject,
        if (examTitle != null && examTitle.trim().isNotEmpty)
          'exam_title': examTitle.trim(),
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> uploadQuestionImage({
    required Uint8List imageBytes,
    required String filename,
    required String contentType,
    required String subject,
    required String examTitle,
    int? sortOrder,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/admin/question-images'),
    );
    if (token != null && token!.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.fields['subject'] = subject;
    request.fields['exam_title'] = examTitle;
    if (sortOrder != null) request.fields['sort_order'] = '$sortOrder';
    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        imageBytes,
        filename: filename,
        contentType: _mediaType(contentType),
      ),
    );

    final streamed = await request.send().timeout(const Duration(seconds: 20));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode >= 200 && streamed.statusCode < 300) {
      return jsonDecode(body) as Map<String, dynamic>;
    }
    throw ApiException(_errorMessage(body), streamed.statusCode);
  }

  Future<Map<String, dynamic>> deleteQuestionImage(int imageId) async {
    final response = await http.delete(
      _uri('/admin/question-images/$imageId'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> checkSideCamera(String sessionId) async {
    final response = await http
        .post(_uri('/proctor/side-camera/check/$sessionId'), headers: _headers)
        .timeout(const Duration(seconds: 5));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> validateSideCamera(String sideCameraUrl) async {
    final response = await http
        .post(
          _uri('/proctor/validate-side-camera'),
          headers: _headers,
          body: jsonEncode({'camera_input': sideCameraUrl}),
        )
        .timeout(const Duration(seconds: 10));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> reconnectSideCamera({
    required String sessionId,
    required String sideCameraUrl,
  }) async {
    final response = await http
        .post(
          _uri('/proctor/side-camera/reconnect/$sessionId'),
          headers: _headers,
          body: jsonEncode({'camera_input': sideCameraUrl}),
        )
        .timeout(const Duration(seconds: 10));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> logClientEvent({
    required String sessionId,
    required String eventType,
    required String message,
    String severity = 'INFO',
    double scoreDelta = 0,
    Map<String, dynamic> metadata = const {},
  }) async {
    final response = await http
        .post(
          _uri('/session/$sessionId/event'),
          headers: _headers,
          body: jsonEncode({
            'event_type': eventType,
            'message': message,
            'severity': severity,
            'score_delta': scoreDelta,
            'metadata': metadata,
          }),
        )
        .timeout(const Duration(seconds: 8));
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> autosaveAnswers({
    required String sessionId,
    required Map<String, String> answers,
  }) async {
    final response = await http.put(
      _uri('/session/$sessionId/autosave'),
      headers: _headers,
      body: jsonEncode({'answers': answers}),
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> submitExam({
    required String sessionId,
    required Map<String, String> answers,
    String reason = 'submitted_by_candidate',
  }) async {
    final response = await http
        .post(
          _uri('/session/$sessionId/submit'),
          headers: _headers,
          body: jsonEncode({'answers': answers, 'reason': reason}),
        )
        .timeout(const Duration(seconds: 18));
    return _decodeMap(response);
  }

  Future<List<dynamic>> getSessions({String? subject}) async {
    final response = await http.get(
      _uri('/admin/sessions', {
        if (subject != null && subject != 'ALL') 'subject': subject,
      }),
      headers: _headers,
    );
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> getSessionDetail(String sessionId) async {
    final response = await http.get(
      _uri('/admin/sessions/$sessionId'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> getDashboardStats() async {
    final response = await http.get(_uri('/admin/stats'), headers: _headers);
    return _decodeMap(response);
  }

  Future<List<dynamic>> getEvents() async {
    final response = await http.get(_uri('/admin/events'), headers: _headers);
    return _decodeList(response);
  }

  Future<Map<String, dynamic>> terminateSession(String sessionId) async {
    final response = await http.post(
      _uri('/admin/session/$sessionId/terminate'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> flagSession(String sessionId) async {
    final response = await http.post(
      _uri('/admin/session/$sessionId/flag'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> approveRejoin(String sessionId) async {
    final response = await http.post(
      _uri('/admin/session/$sessionId/approve-rejoin'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> denyRejoin(String sessionId) async {
    final response = await http.post(
      _uri('/admin/session/$sessionId/deny-rejoin'),
      headers: _headers,
    );
    return _decodeMap(response);
  }

  String getStreamUrl(String sessionId) => '$baseUrl/admin/stream/$sessionId';

  String getSideStreamUrl(String sessionId) =>
      '$baseUrl/admin/stream/$sessionId/side';

  String getSnapshotUrl(String sessionId, int cacheKey) =>
      '$baseUrl/admin/snapshot/$sessionId?t=$cacheKey';

  String getFrontRawSnapshotUrl(String sessionId, int cacheKey) =>
      '$baseUrl/admin/snapshot/$sessionId/front-raw?t=$cacheKey';

  String getSideSnapshotUrl(String sessionId, int cacheKey) =>
      '$baseUrl/admin/snapshot/$sessionId/side?t=$cacheKey';

  String getStudentSideStreamUrl(String sessionId) {
    final query = token != null && token!.isNotEmpty
        ? '?token=${Uri.encodeQueryComponent(token!)}'
        : '';
    return '$baseUrl/session/$sessionId/side-stream$query';
  }

  String getStudentSideSnapshotUrl(String sessionId, int cacheKey) {
    final query = {
      't': '$cacheKey',
      if (token != null && token!.isNotEmpty) 'token': token!,
    };
    return Uri.parse(
      '$baseUrl/session/$sessionId/side-snapshot',
    ).replace(queryParameters: query).toString();
  }

  String getQuestionImageUrl(int imageId) {
    final query = token != null && token!.isNotEmpty
        ? '?token=${Uri.encodeQueryComponent(token!)}'
        : '';
    return '$baseUrl/session/question-images/$imageId/file$query';
  }

  String getQuestionAttachmentUrl(int questionId) {
    final query = token != null && token!.isNotEmpty
        ? '?token=${Uri.encodeQueryComponent(token!)}'
        : '';
    return '$baseUrl/session/questions/$questionId/image$query';
  }

  String getTeacherResultsExportUrl({
    required String format,
    int? subjectId,
    String? branch,
    String? division,
    String? search,
  }) {
    final query = {
      'format': format,
      if (subjectId != null) 'subject_id': '$subjectId',
      if (branch != null && branch.isNotEmpty) 'branch': branch,
      if (division != null && division.isNotEmpty) 'division': division,
      if (search != null && search.isNotEmpty) 'search': search,
      if (token != null && token!.isNotEmpty) 'token': token!,
    };
    return Uri.parse(
      '$baseUrl/teacher/results/export',
    ).replace(queryParameters: query).toString();
  }

  String adminWebSocketUrl() => _ws('/ws/admin');

  String sessionWebSocketUrl(String sessionId) => _ws('/ws/session/$sessionId');

  String _ws(String path) {
    return ApiConfig.webSocketUrl(
      path,
      token: token != null && token!.isNotEmpty ? token : null,
    );
  }

  Map<String, dynamic> _decodeMap(http.Response response) {
    _debugResponse(response);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return {};
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw ApiException(_errorMessage(response.body), response.statusCode);
  }

  List<dynamic> _decodeList(http.Response response) {
    _debugResponse(response);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return jsonDecode(response.body) as List<dynamic>;
    }
    throw ApiException(_errorMessage(response.body), response.statusCode);
  }

  List<Map<String, dynamic>> _decodeMapList(http.Response response) {
    _debugResponse(response);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      final decoded = jsonDecode(response.body) as List<dynamic>;
      return decoded
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList(growable: false);
    }
    throw ApiException(_errorMessage(response.body), response.statusCode);
  }

  String _errorMessage(String body) {
    try {
      final decoded = jsonDecode(body);
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      return detail?.toString() ?? 'Request failed';
    } catch (_) {
      return body.isEmpty ? 'Request failed' : body;
    }
  }

  void _debugResponse(http.Response response) {
    debugPrint(
      '[API] ${response.request?.method ?? 'HTTP'} '
      '${response.request?.url.path ?? ''} -> ${response.statusCode} '
      '${response.body.length > 500 ? '${response.body.substring(0, 500)}...' : response.body}',
    );
  }

  MediaType _mediaType(String contentType) {
    final parts = contentType.split('/');
    if (parts.length != 2) return MediaType('application', 'octet-stream');
    return MediaType(parts[0], parts[1]);
  }
}
