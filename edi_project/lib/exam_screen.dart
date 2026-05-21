import 'dart:async';
import 'dart:convert';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'app_state.dart';

class ExamScreen extends StatefulWidget {
  const ExamScreen({
    super.key,
    required this.examTitle,
    required this.subject,
    required this.sideCameraUrl,
    required this.studentId,
    required this.studentName,
  });

  final String examTitle;
  final String subject;
  final String sideCameraUrl;
  final String studentId;
  final String studentName;

  @override
  State<ExamScreen> createState() => _ExamScreenState();
}

class _ExamScreenState extends State<ExamScreen> with WidgetsBindingObserver {
  final List<_Question> _questions = const [
    _Question('Which algorithm is supervised learning?', [
      'K-Means',
      'Linear Regression',
      'PCA',
      'Association Rules',
    ]),
    _Question('Which layer secures HTTPS traffic?', [
      'Transport',
      'Presentation',
      'Network',
      'Physical',
    ]),
    _Question('What does a confusion matrix summarize?', [
      'Disk usage',
      'Model predictions',
      'Network packets',
      'CPU scheduling',
    ]),
    _Question('Which metric is useful for imbalanced classes?', [
      'Accuracy only',
      'F1 score',
      'Clock speed',
      'Bandwidth',
    ]),
    _Question('What is phishing?', [
      'A social engineering attack',
      'A compiler phase',
      'A sorting method',
      'A database index',
    ]),
  ];

  CameraController? _cameraController;
  Future<void>? _cameraInitialization;
  WebSocketChannel? _channel;
  Timer? _captureTimer;
  Timer? _sideCheckTimer;
  Timer? _clockTimer;
  Timer? _reconnectTimer;

  late final String _sessionId;
  final Map<String, String> _answers = {};

  int _currentIndex = 0;
  int _remainingSeconds = 60 * 60;
  double _cheatScore = 0;
  bool _cameraReady = false;
  bool _monitoringStarted = false;
  bool _uploading = false;
  bool _checkingSideCamera = false;
  bool _connected = false;
  bool _submitting = false;
  DateTime? _lastDisconnectLogAt;
  String? _cameraError;
  String _aiMessage = 'AI monitoring active';
  String _candidateStatus = 'MONITORING';
  String _sideCameraStatus = 'UNKNOWN';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _sessionId = '${widget.studentId}-${DateTime.now().millisecondsSinceEpoch}';
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    unawaited(_ensureCameraInitialized());
    _startExam();
  }

  Future<void> _startExam() async {
    final app = context.read<AppState>();
    try {
      final session = await app.api.startSession(
        sessionId: _sessionId,
        studentId: widget.studentId,
        studentName: widget.studentName,
        examTitle: widget.examTitle,
        subject: widget.subject,
        sideCameraUrl: widget.sideCameraUrl,
      );
      _connectWebSocket();
      _handleRealtime(session);
      if (session['status'] == 'REJOIN_PENDING') {
        setState(() {
          _connected = true;
          _aiMessage = 'Waiting for proctor approval to rejoin this exam.';
        });
        return;
      }
      await _activateMonitoring();
    } catch (error) {
      if (mounted) {
        setState(() {
          _connected = false;
          _aiMessage = 'Backend connection failed: $error';
        });
      }
    }
  }

  Future<void> _activateMonitoring() async {
    if (_monitoringStarted) return;
    _monitoringStarted = true;
    _startSideCameraWatchdog();
    _startClock();
    await _ensureCameraInitialized();
    if (_cameraReady) {
      _startFrameUpload();
    }
  }

  Future<void> _ensureCameraInitialized() {
    return _cameraInitialization ??= _initializeCamera();
  }

  Future<void> _initializeCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        _setCameraFailure('No front camera detected');
        return;
      }

      final front = cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      final controller = CameraController(
        front,
        ResolutionPreset.low,
        enableAudio: false,
      );
      _cameraController = controller;
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _cameraError = null;
        _cameraReady = true;
      });
    } on CameraException catch (error) {
      _setCameraFailure(
        'Front camera unavailable: ${error.description ?? error.code}',
      );
    } catch (error) {
      _setCameraFailure('Front camera unavailable: $error');
    }
  }

  void _setCameraFailure(String message) {
    if (!mounted) return;
    setState(() {
      _cameraError = message;
      _cameraReady = false;
      _aiMessage = message;
    });
  }

  void _connectWebSocket() {
    try {
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(
        Uri.parse(context.read<AppState>().api.sessionWebSocketUrl(_sessionId)),
      );
      setState(() => _connected = true);
      _channel!.stream.listen(
        (data) =>
            _handleRealtime(jsonDecode(data as String) as Map<String, dynamic>),
        onError: (_) => _scheduleReconnect(),
        onDone: _scheduleReconnect,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (!mounted) return;
    setState(() => _connected = false);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connectWebSocket);
  }

  void _handleRealtime(Map<String, dynamic> data) {
    if (!mounted) return;
    setState(() {
      _cheatScore = ((data['cheat_score'] ?? _cheatScore) as num).toDouble();
      _sideCameraStatus =
          (data['side_camera_status'] ?? _sideCameraStatus).toString();
      _candidateStatus =
          (data['candidate_status'] ?? data['status'] ?? _candidateStatus)
              .toString();
      _aiMessage = (data['message'] ?? data['cheat_message'] ?? _aiMessage)
          .toString();
    });
    if (_candidateStatus == 'MONITORING' && !_monitoringStarted) {
      _activateMonitoring();
    }
    if (_candidateStatus == 'AUTO_SUBMIT_REQUIRED' || _cheatScore >= 95) {
      _submitExam(reason: 'auto_submitted_cheating_threshold');
    }
    if (_candidateStatus == 'TERMINATED') {
      _showClosedDialog('This exam session was terminated by the proctor.');
    }
    if (_candidateStatus == 'REJOIN_DENIED') {
      _showClosedDialog('Your request to rejoin this exam was denied.');
    }
  }

  void _startClock() {
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      if (_remainingSeconds <= 1) {
        _submitExam(reason: 'time_expired');
      } else {
        setState(() => _remainingSeconds--);
      }
    });
  }

  void _startFrameUpload() {
    if (_captureTimer != null) return;
    unawaited(_uploadFrontFrame());
    _captureTimer = Timer.periodic(
      const Duration(seconds: 2),
      (_) => _uploadFrontFrame(),
    );
  }

  Future<void> _uploadFrontFrame() async {
    final controller = _cameraController;
    if (_uploading ||
        controller == null ||
        !controller.value.isInitialized ||
        controller.value.isTakingPicture) {
      return;
    }

    _uploading = true;
    final api = context.read<AppState>().api;
    try {
      final image = await controller.takePicture();
      final bytes = await image.readAsBytes();
      final result = await api.uploadFrame(
        bytes,
        _sessionId,
        filename: image.name.isEmpty ? 'front-camera.jpg' : image.name,
      );
      _handleRealtime(result);
      if (mounted) setState(() => _connected = true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _connected = false;
          _aiMessage = 'Network interrupted. Reconnecting monitoring channel.';
        });
      }
      final now = DateTime.now();
      final shouldLogDisconnect = _lastDisconnectLogAt == null ||
          now.difference(_lastDisconnectLogAt!) > const Duration(seconds: 20);
      if (shouldLogDisconnect) {
        _lastDisconnectLogAt = now;
        await _logEvent(
          'DISCONNECT',
          'Candidate monitoring connection interrupted',
          severity: 'MEDIUM',
          scoreDelta: 4,
        );
      }
    } finally {
      _uploading = false;
    }
  }

  void _startSideCameraWatchdog() {
    _sideCheckTimer?.cancel();
    _sideCheckTimer = Timer.periodic(const Duration(seconds: 1), (_) async {
      if (!_monitoringStarted || _submitting || _checkingSideCamera) return;
      _checkingSideCamera = true;
      try {
        final result = await context.read<AppState>().api.checkSideCamera(
          _sessionId,
        );
        _handleRealtime(result);
      } catch (_) {
      } finally {
        _checkingSideCamera = false;
      }
    });
  }

  Future<void> _logEvent(
    String type,
    String message, {
    String severity = 'INFO',
    double scoreDelta = 0,
  }) async {
    try {
      await context.read<AppState>().api.logClientEvent(
        sessionId: _sessionId,
        eventType: type,
        message: message,
        severity: severity,
        scoreDelta: scoreDelta,
      );
    } catch (_) {}
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.inactive ||
        state == AppLifecycleState.hidden) {
      _logEvent(
        'TAB_SWITCH',
        'Candidate left the exam window',
        severity: 'HIGH',
        scoreDelta: 15,
      );
    }
  }

  Future<void> _submitExam({String reason = 'submitted_by_candidate'}) async {
    if (_submitting) return;
    if (!_monitoringStarted) return;
    setState(() => _submitting = true);
    try {
      await context.read<AppState>().api.submitExam(
        sessionId: _sessionId,
        answers: _answers,
        reason: reason,
      );
      if (!mounted) return;
      await _showClosedDialog(
        reason == 'submitted_by_candidate'
            ? 'Exam submitted successfully.'
            : 'Exam auto-submitted.',
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Submit failed: $error')));
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _showClosedDialog(String message) async {
    _captureTimer?.cancel();
    _sideCheckTimer?.cancel();
    _clockTimer?.cancel();
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Exam Closed'),
        content: Text(message),
        actions: [
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              Navigator.pop(context);
            },
            child: const Text('Return'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _captureTimer?.cancel();
    _sideCheckTimer?.cancel();
    _clockTimer?.cancel();
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    _cameraController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final question = _questions[_currentIndex];
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: false,
          title: Text(widget.examTitle),
          actions: [
            _StatusChip(
              icon: _connected ? Icons.cloud_done : Icons.cloud_off,
              label: _connected ? 'Connected' : 'Reconnecting',
              color: _connected ? Colors.greenAccent : Colors.orangeAccent,
            ),
            const SizedBox(width: 8),
            _StatusChip(
              icon: Icons.timer,
              label: _timeText,
              color: Colors.redAccent,
            ),
            const SizedBox(width: 12),
          ],
        ),
        body: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 980;
            final content = [
              Expanded(flex: 3, child: _buildQuestionPanel(question)),
              const SizedBox(width: 16, height: 16),
              SizedBox(
                width: wide ? 340 : double.infinity,
                child: _buildMonitorPanel(),
              ),
            ];
            return Padding(
              padding: const EdgeInsets.all(18),
              child: wide
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: content,
                    )
                  : Column(children: content),
            );
          },
        ),
      ),
    );
  }

  Widget _buildQuestionPanel(_Question question) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  'Question ${_currentIndex + 1} of ${_questions.length}',
                  style: const TextStyle(color: Colors.white70),
                ),
                const Spacer(),
                Text(
                  '${((_currentIndex + 1) / _questions.length * 100).round()}% complete',
                ),
              ],
            ),
            const SizedBox(height: 10),
            LinearProgressIndicator(
              value: (_currentIndex + 1) / _questions.length,
            ),
            const SizedBox(height: 24),
            Text(
              question.title,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 18),
            Expanded(
              child: RadioGroup<String>(
                groupValue: _answers[_currentIndex.toString()],
                onChanged: (value) => setState(
                  () => _answers[_currentIndex.toString()] = value ?? '',
                ),
                child: ListView.separated(
                  itemCount: question.options.length,
                  separatorBuilder: (context, index) =>
                      const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final option = question.options[index];
                    return RadioListTile<String>(
                      value: option,
                      title: Text(option),
                      tileColor: const Color(0xFF0F172A),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    );
                  },
                ),
              ),
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: List.generate(
                _questions.length,
                (index) => ChoiceChip(
                  selected: index == _currentIndex,
                  label: Text('${index + 1}'),
                  avatar: _answers.containsKey(index.toString())
                      ? const Icon(Icons.check, size: 16)
                      : null,
                  onSelected: (_) => setState(() => _currentIndex = index),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                OutlinedButton.icon(
                  onPressed: _currentIndex == 0
                      ? null
                      : () => setState(() => _currentIndex--),
                  icon: const Icon(Icons.chevron_left),
                  label: const Text('Previous'),
                ),
                const SizedBox(width: 10),
                OutlinedButton.icon(
                  onPressed: _currentIndex == _questions.length - 1
                      ? null
                      : () => setState(() => _currentIndex++),
                  icon: const Icon(Icons.chevron_right),
                  label: const Text('Next'),
                ),
                const Spacer(),
                FilledButton.icon(
                  onPressed: _submitting ? null : () => _submitExam(),
                  icon: _submitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.task_alt),
                  label: const Text('Submit Exam'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMonitorPanel() {
    return Column(
      children: [
        AspectRatio(
          aspectRatio: 4 / 3,
          child: Container(
            decoration: BoxDecoration(
              color: Colors.black,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.cyanAccent, width: 2),
            ),
            clipBehavior: Clip.antiAlias,
            child: _buildFrontCameraPreview(),
          ),
        ),
        const SizedBox(height: 12),
        AspectRatio(
          aspectRatio: 4 / 3,
          child: Container(
            decoration: BoxDecoration(
              color: Colors.black,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white24),
            ),
            clipBehavior: Clip.antiAlias,
            child: _SnapshotFeed(
              sessionId: _sessionId,
              side: true,
              emptyText: 'Waiting for side camera feed',
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Icon(Icons.radar, color: Colors.cyanAccent),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        'AI Monitoring Active',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                _Metric(
                  label: 'Candidate status',
                  value: _studentCandidateStatus,
                  color: Colors.cyanAccent,
                ),
                _Metric(
                  label: 'Side camera',
                  value: _sideCameraStatus,
                  color: _sideCameraStatus == 'ONLINE'
                      ? Colors.greenAccent
                      : Colors.orangeAccent,
                ),
                const Divider(height: 22),
                Text(
                  _studentMonitoringMessage,
                  style: const TextStyle(
                    color: Colors.white70,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  String get _timeText {
    final minutes = (_remainingSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (_remainingSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  String get _studentMonitoringMessage {
    if (_cameraError != null) return _cameraError!;
    if (!_connected) return _aiMessage;
    if (!_monitoringStarted) return _aiMessage;
    return _sideCameraStatus == 'ONLINE'
        ? 'Monitoring connection active.'
        : 'Waiting for side camera connection.';
  }

  String get _studentCandidateStatus {
    return switch (_candidateStatus) {
      'REJOIN_PENDING' => 'WAITING FOR APPROVAL',
      'REJOIN_DENIED' => 'REJOIN DENIED',
      'SUBMITTED' => 'SUBMITTED',
      'TERMINATED' => 'CLOSED',
      _ => 'MONITORING',
    };
  }

  Widget _buildFrontCameraPreview() {
    if (_cameraReady && _cameraController != null) {
      return CameraPreview(_cameraController!);
    }
    if (_cameraError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            _cameraError!,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white70),
          ),
        ),
      );
    }
    return const Center(child: CircularProgressIndicator());
  }
}

class _SnapshotFeed extends StatefulWidget {
  const _SnapshotFeed({
    required this.sessionId,
    required this.side,
    required this.emptyText,
  });

  final String sessionId;
  final bool side;
  final String emptyText;

  @override
  State<_SnapshotFeed> createState() => _SnapshotFeedState();
}

class _SnapshotFeedState extends State<_SnapshotFeed> {
  Timer? _timer;
  int _cacheKey = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 400), (_) {
      if (mounted) setState(() => _cacheKey++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final url = widget.side
        ? api.getSideSnapshotUrl(widget.sessionId, _cacheKey)
        : api.getSnapshotUrl(widget.sessionId, _cacheKey);
    return Image.network(
      url,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      webHtmlElementStrategy: WebHtmlElementStrategy.prefer,
      errorBuilder: (context, error, stackTrace) => Center(
        child: Text(
          widget.emptyText,
          style: const TextStyle(color: Colors.white54),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _Question {
  const _Question(this.title, this.options);

  final String title;
  final List<String> options;
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(30),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(color: color, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Expanded(
            child: Text(label, style: const TextStyle(color: Colors.white60)),
          ),
          Text(
            value,
            style: TextStyle(color: color, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}
