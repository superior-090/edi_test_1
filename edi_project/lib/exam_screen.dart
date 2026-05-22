import 'dart:async';
import 'dart:convert';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'app_state.dart';
import 'design_system.dart';
import 'exam_copy_guard.dart';
import 'side_camera_stream.dart';

void _noop() {}

class ExamScreen extends StatefulWidget {
  const ExamScreen({
    super.key,
    required this.examTitle,
    this.examId,
    this.durationMinutes = 60,
    required this.subject,
    required this.sideCameraUrl,
    required this.studentId,
    required this.studentName,
  });

  final String examTitle;
  final int? examId;
  final int durationMinutes;
  final String subject;
  final String sideCameraUrl;
  final String studentId;
  final String studentName;

  @override
  State<ExamScreen> createState() => _ExamScreenState();
}

class _ExamScreenState extends State<ExamScreen> with WidgetsBindingObserver {
  static const List<_Question> _fallbackQuestions = [
    _Question.text('Which algorithm is supervised learning?', [
      'K-Means',
      'Linear Regression',
      'PCA',
      'Association Rules',
    ]),
    _Question.text('Which layer secures HTTPS traffic?', [
      'Transport',
      'Presentation',
      'Network',
      'Physical',
    ]),
    _Question.text('What does a confusion matrix summarize?', [
      'Disk usage',
      'Model predictions',
      'Network packets',
      'CPU scheduling',
    ]),
    _Question.text('Which metric is useful for imbalanced classes?', [
      'Accuracy only',
      'F1 score',
      'Clock speed',
      'Bandwidth',
    ]),
    _Question.text('What is phishing?', [
      'A social engineering attack',
      'A compiler phase',
      'A sorting method',
      'A database index',
    ]),
  ];

  List<_Question> _questions = _fallbackQuestions;

  CameraController? _cameraController;
  Future<void>? _cameraInitialization;
  WebSocketChannel? _channel;
  Timer? _captureTimer;
  Timer? _sideCheckTimer;
  Timer? _clockTimer;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;
  Timer? _autosaveTimer;

  late final String _sessionId;
  late String _sideCameraUrl;
  final Map<String, String> _answers = {};
  final Set<String> _reviewQuestionKeys = {};

  int _currentIndex = 0;
  late int _remainingSeconds;
  bool _cameraReady = false;
  bool _monitoringStarted = false;
  bool _uploading = false;
  bool _checkingSideCamera = false;
  bool _connected = false;
  bool _loadingQuestions = true;
  bool _submitting = false;
  bool _submitted = false;
  bool _closingDialogVisible = false;
  bool _sideReconnectBusy = false;
  bool _sessionStarted = false;
  bool _startingSession = false;
  bool _disposed = false;
  DateTime? _lastDisconnectLogAt;
  String? _cameraError;
  String? _sessionStartError;
  String _candidateStatus = 'MONITORING';
  String _sideCameraStatus = 'UNKNOWN';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _sessionId = '${widget.studentId}-${DateTime.now().millisecondsSinceEpoch}';
    _remainingSeconds = widget.durationMinutes * 60;
    _sideCameraUrl = widget.sideCameraUrl;
    enableExamCopyGuard();
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    unawaited(_loadQuestions());
    unawaited(_ensureCameraInitialized());
    _startExam();
  }

  Future<void> _loadQuestions() async {
    try {
      final api = context.read<AppState>().api;
      if (widget.examId != null) {
        final questionRows = await api.getExamQuestions(widget.examId!);
        if (questionRows.isNotEmpty) {
          if (!mounted) return;
          setState(() {
            _questions = questionRows
                .map<_Question>(
                  (map) => _Question.fromQuestionJson(
                    map,
                    imageUrlForId: api.getQuestionAttachmentUrl,
                  ),
                )
                .toList(growable: false);
            _currentIndex = 0;
            _loadingQuestions = false;
          });
          return;
        }
      }
      final rows = await api.getQuestionImages(
        examId: widget.examId,
        subject: widget.subject,
        examTitle: widget.examTitle,
      );
      if (!mounted) return;
      final List<_Question> imageQuestions = rows
          .map<_Question>(
            (map) => _Question.fromImageJson(
              map,
              imageUrlForId: api.getQuestionImageUrl,
            ),
          )
          .toList(growable: false);
      setState(() {
        _questions = imageQuestions.isEmpty
            ? _fallbackQuestions
            : imageQuestions;
        _currentIndex = 0;
        _loadingQuestions = false;
      });
    } catch (error, stackTrace) {
      debugPrint('Question image load failed: $error\n$stackTrace');
      if (mounted) {
        setState(() {
          _questions = _fallbackQuestions;
          _loadingQuestions = false;
        });
      }
    }
  }

  Future<void> _startExam() async {
    if (_startingSession || _sessionStarted) return;
    if (mounted) {
      setState(() {
        _startingSession = true;
        _sessionStartError = null;
      });
    } else {
      _startingSession = true;
      _sessionStartError = null;
    }
    final app = context.read<AppState>();
    try {
      debugPrint('Starting backend exam session: $_sessionId');
      final session = await app.api.startSession(
        sessionId: _sessionId,
        examId: widget.examId,
        studentId: widget.studentId,
        studentName: widget.studentName,
        examTitle: widget.examTitle,
        subject: widget.subject,
        sideCameraUrl: _sideCameraUrl,
      );
      if (!mounted) return;
      setState(() {
        _sessionStarted = true;
        _startingSession = false;
        _sessionStartError = null;
      });
      _connectWebSocket();
      _handleRealtime(session);
      if (session['status'] == 'REJOIN_PENDING') {
        setState(() {
          _connected = true;
        });
        return;
      }
      await _activateMonitoring();
    } catch (error, stackTrace) {
      debugPrint('Start exam session failed: $error\n$stackTrace');
      if (mounted) {
        setState(() {
          _connected = false;
          _sessionStarted = false;
          _startingSession = false;
          _sessionStartError = error.toString();
        });
      }
    }
  }

  Future<void> _activateMonitoring() async {
    if (_monitoringStarted) return;
    _monitoringStarted = true;
    _startSideCameraWatchdog();
    _startClock();
    _startAutosave();
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
    });
  }

  void _connectWebSocket() {
    try {
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(
        Uri.parse(context.read<AppState>().api.sessionWebSocketUrl(_sessionId)),
      );
      setState(() => _connected = true);
      _heartbeatTimer?.cancel();
      _heartbeatTimer = Timer.periodic(const Duration(seconds: 20), (_) {
        try {
          _channel?.sink.add(jsonEncode({'type': 'ping'}));
        } catch (error, stackTrace) {
          debugPrint('Exam websocket ping failed: $error\n$stackTrace');
          _scheduleReconnect();
        }
      });
      _channel!.stream.listen(
        (data) {
          try {
            final decoded = jsonDecode(data as String) as Map<String, dynamic>;
            if (decoded['type'] == 'pong') return;
            _handleRealtime(decoded);
          } catch (error, stackTrace) {
            debugPrint('Exam realtime decode failed: $error\n$stackTrace');
          }
        },
        onError: (error, stackTrace) {
          debugPrint('Exam websocket error: $error\n$stackTrace');
          _scheduleReconnect();
        },
        onDone: _scheduleReconnect,
      );
    } catch (error, stackTrace) {
      debugPrint('Exam websocket connect failed: $error\n$stackTrace');
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (!mounted || _submitted || _disposed) return;
    setState(() => _connected = false);
    _heartbeatTimer?.cancel();
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connectWebSocket);
  }

  void _handleRealtime(Map<String, dynamic> data) {
    if (!mounted) return;
    setState(() {
      _sideCameraStatus = (data['side_camera_status'] ?? _sideCameraStatus)
          .toString();
      _candidateStatus =
          (data['candidate_status'] ?? data['status'] ?? _candidateStatus)
              .toString();
    });
    if (_candidateStatus == 'MONITORING' && !_monitoringStarted) {
      _activateMonitoring();
    }
    if (_candidateStatus == 'AUTO_SUBMIT_REQUIRED' && !_submitted) {
      unawaited(_submitExam(reason: 'auto_submitted_cheating_threshold'));
    }
    if (_candidateStatus == 'TERMINATED') {
      unawaited(_showClosedDialog('This exam session is closed.'));
    }
    if (_candidateStatus == 'REJOIN_DENIED') {
      unawaited(_showClosedDialog('This exam session is closed.'));
    }
    if (_candidateStatus == 'SUBMITTED' && !_submitted) {
      _submitted = true;
      unawaited(_showClosedDialog('Exam submitted successfully.'));
    }
  }

  void _startClock() {
    _clockTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      if (_remainingSeconds <= 1) {
        unawaited(_submitExam(reason: 'time_expired'));
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

  void _startAutosave() {
    _autosaveTimer?.cancel();
    _autosaveTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => unawaited(_autosaveAnswers()),
    );
  }

  Future<void> _autosaveAnswers() async {
    if (_answers.isEmpty || _submitted || _submitting) return;
    try {
      await context.read<AppState>().api.autosaveAnswers(
        sessionId: _sessionId,
        answers: _answers,
      );
    } catch (error, stackTrace) {
      debugPrint('Exam autosave failed: $error\n$stackTrace');
    }
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
      debugPrint('Front frame uploaded; session=$_sessionId');
      _handleRealtime(result);
      if (mounted) setState(() => _connected = true);
    } catch (error, stackTrace) {
      debugPrint('Front frame upload failed: $error\n$stackTrace');
      if (mounted) {
        setState(() {
          _connected = false;
        });
      }
      final now = DateTime.now();
      final shouldLogDisconnect =
          _lastDisconnectLogAt == null ||
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
    _sideCheckTimer = Timer.periodic(const Duration(seconds: 10), (_) async {
      if (!_monitoringStarted || _submitting || _checkingSideCamera) return;
      _checkingSideCamera = true;
      try {
        final api = context.read<AppState>().api;
        final result = await api.checkSideCamera(_sessionId);
        _handleRealtime(result);
      } catch (error, stackTrace) {
        debugPrint('Side camera check failed: $error\n$stackTrace');
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
    } catch (error, stackTrace) {
      debugPrint('Client event log failed: $error\n$stackTrace');
    }
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
    if (_submitting || _submitted) return;
    if (reason == 'submitted_by_candidate') {
      final confirmed = await _confirmSubmit();
      if (confirmed != true || !mounted) return;
    }
    final sessionReady = await _ensureSessionStarted();
    if (!sessionReady) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              _sessionStartError == null
                  ? 'Starting exam session. Please try again.'
                  : 'Cannot submit yet: $_sessionStartError',
            ),
          ),
        );
      }
      return;
    }
    _captureTimer?.cancel();
    _sideCheckTimer?.cancel();
    _clockTimer?.cancel();
    _autosaveTimer?.cancel();
    _captureTimer = null;
    _sideCheckTimer = null;
    _clockTimer = null;
    _autosaveTimer = null;
    setState(() => _submitting = true);
    final api = context.read<AppState>().api;
    try {
      final result = await api.submitExam(
        sessionId: _sessionId,
        answers: _answers,
        reason: reason,
      );
      _handleRealtime(result);
      if (!mounted) return;
      setState(() => _submitted = true);
      await _showClosedDialog(
        reason == 'submitted_by_candidate'
            ? 'Exam submitted successfully.'
            : 'Exam auto-submitted.',
      );
    } on TimeoutException catch (error, stackTrace) {
      debugPrint('Submit exam timed out: $error\n$stackTrace');
      if (mounted) {
        _restartSubmitTimersIfNeeded();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Submission timed out. Check connection and retry.'),
          ),
        );
      }
    } catch (error, stackTrace) {
      debugPrint('Submit exam failed: $error\n$stackTrace');
      if (mounted) {
        _restartSubmitTimersIfNeeded();
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Submit failed: $error')));
      }
    } finally {
      if (mounted && !_submitted) setState(() => _submitting = false);
    }
  }

  Future<bool> _ensureSessionStarted() async {
    if (_sessionStarted) return true;
    if (_startingSession) {
      for (var i = 0; i < 40 && _startingSession && mounted; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 250));
      }
      if (_sessionStarted) return true;
    }
    await _startExam();
    return _sessionStarted;
  }

  Future<bool?> _confirmSubmit() {
    return showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Submit Exam?'),
        content: const Text(
          'Your answers will be submitted and the exam will close.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Submit'),
          ),
        ],
      ),
    );
  }

  void _restartSubmitTimersIfNeeded() {
    if (_submitted || !_monitoringStarted) return;
    _startSideCameraWatchdog();
    if (_clockTimer == null || !_clockTimer!.isActive) _startClock();
    if (_cameraReady) _startFrameUpload();
  }

  Future<void> _showClosedDialog(String message) async {
    if (!mounted || _closingDialogVisible) return;
    _closingDialogVisible = true;
    _captureTimer?.cancel();
    _sideCheckTimer?.cancel();
    _clockTimer?.cancel();
    _autosaveTimer?.cancel();
    _captureTimer = null;
    _sideCheckTimer = null;
    _clockTimer = null;
    _autosaveTimer = null;
    _heartbeatTimer?.cancel();
    _reconnectTimer?.cancel();
    await _channel?.sink.close();
    if (!mounted) return;
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
              Navigator.of(context).pushNamedAndRemoveUntil(
                '/student_home',
                (route) => route.settings.name == '/login',
              );
            },
            child: const Text('Return'),
          ),
        ],
      ),
    );
    _closingDialogVisible = false;
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _disposed = true;
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _captureTimer?.cancel();
    _sideCheckTimer?.cancel();
    _clockTimer?.cancel();
    _reconnectTimer?.cancel();
    _heartbeatTimer?.cancel();
    _autosaveTimer?.cancel();
    _channel?.sink.close();
    _cameraController?.dispose();
    disableExamCopyGuard();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final question = _questions[_currentIndex];
    return Focus(
      autofocus: true,
      onKeyEvent: _handleExamKey,
      child: PopScope(
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
          body: AiGradientBackground(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 980;
                final content = Padding(
                  padding: const EdgeInsets.all(18),
                  child: wide
                      ? Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Expanded(
                              flex: 3,
                              child: _buildQuestionPanel(question),
                            ),
                            const SizedBox(width: 16),
                            SizedBox(
                              width: 340,
                              child: SingleChildScrollView(
                                child: _buildMonitorPanel(),
                              ),
                            ),
                          ],
                        )
                      : ListView(
                          children: [
                            SizedBox(
                              height: (constraints.maxHeight * 0.58).clamp(
                                420.0,
                                620.0,
                              ),
                              child: _buildQuestionPanel(question),
                            ),
                            const SizedBox(height: 16),
                            _buildMonitorPanel(),
                          ],
                        ),
                );
                return Stack(
                  children: [
                    content,
                    if (_sideCameraNeedsReconnect) _buildSideCameraOverlay(),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  KeyEventResult _handleExamKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    final key = event.logicalKey;
    final pressed = HardwareKeyboard.instance.logicalKeysPressed;
    final command =
        pressed.contains(LogicalKeyboardKey.controlLeft) ||
        pressed.contains(LogicalKeyboardKey.controlRight) ||
        pressed.contains(LogicalKeyboardKey.metaLeft) ||
        pressed.contains(LogicalKeyboardKey.metaRight);
    final blocked = {
      LogicalKeyboardKey.keyA,
      LogicalKeyboardKey.keyC,
      LogicalKeyboardKey.keyP,
      LogicalKeyboardKey.keyS,
      LogicalKeyboardKey.keyU,
      LogicalKeyboardKey.keyV,
      LogicalKeyboardKey.keyX,
    };
    if (key == LogicalKeyboardKey.f12 || (command && blocked.contains(key))) {
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  Widget _buildQuestionPanel(_Question question) {
    return GlassCard(
      borderColor: AiColors.cyan.withValues(alpha: 0.2),
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
            Expanded(
              child: _loadingQuestions
                  ? const Center(child: CircularProgressIndicator())
                  : question.isImageOnly
                  ? _buildImageQuestion(question)
                  : _buildTextQuestion(question),
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
                  avatar:
                      _answers.containsKey(_questions[index].answerKey(index))
                      ? const Icon(Icons.check, size: 16)
                      : _reviewQuestionKeys.contains(
                          _questions[index].answerKey(index),
                        )
                      ? const Icon(Icons.flag, size: 16)
                      : null,
                  onSelected: (_) => setState(() => _currentIndex = index),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Flexible(
                  child: OutlinedButton.icon(
                    onPressed: _currentIndex == 0
                        ? null
                        : () => setState(() => _currentIndex--),
                    icon: const Icon(Icons.chevron_left),
                    label: const Text('Previous'),
                  ),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: OutlinedButton.icon(
                    onPressed: () {
                      final answerKey = question.answerKey(_currentIndex);
                      setState(() {
                        if (!_reviewQuestionKeys.remove(answerKey)) {
                          _reviewQuestionKeys.add(answerKey);
                        }
                      });
                    },
                    icon: const Icon(Icons.flag),
                    label: Text(
                      _reviewQuestionKeys.contains(
                            question.answerKey(_currentIndex),
                          )
                          ? 'Unmark'
                          : 'Review',
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: OutlinedButton.icon(
                    onPressed: _currentIndex == _questions.length - 1
                        ? null
                        : () => setState(() => _currentIndex++),
                    icon: const Icon(Icons.chevron_right),
                    label: const Text('Next'),
                  ),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
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
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildImageQuestion(_Question question) {
    final answerKey = question.answerKey(_currentIndex);
    return Column(
      children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: ColoredBox(
              color: Colors.black,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  InteractiveViewer(
                    minScale: 0.8,
                    maxScale: 3.0,
                    child: Center(
                      child: Image.network(
                        question.imageUrl!,
                        fit: BoxFit.contain,
                        gaplessPlayback: true,
                        filterQuality: FilterQuality.high,
                        errorBuilder: (context, error, stackTrace) =>
                            const _FeedPlaceholder(
                              text: 'Question image unavailable',
                              loading: false,
                              onRetry: _noop,
                            ),
                      ),
                    ),
                  ),
                  IgnorePointer(
                    child: _WatermarkOverlay(
                      studentName: widget.studentName,
                      studentId: widget.studentId,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 14),
        TextFormField(
          key: ValueKey('answer-$answerKey'),
          initialValue: _answers[answerKey] ?? '',
          minLines: 2,
          maxLines: 4,
          onChanged: (value) => _answers[answerKey] = value,
          decoration: const InputDecoration(
            labelText: 'Answer',
            prefixIcon: Icon(Icons.edit_note),
          ),
        ),
      ],
    );
  }

  Widget _buildTextQuestion(_Question question) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (question.imageUrl != null) ...[
          SizedBox(
            height: 180,
            width: double.infinity,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: ColoredBox(
                color: Colors.black,
                child: Image.network(
                  question.imageUrl!,
                  fit: BoxFit.contain,
                  errorBuilder: (context, error, stackTrace) =>
                      const _FeedPlaceholder(
                        text: 'Question image unavailable',
                        loading: false,
                        onRetry: _noop,
                      ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
        ],
        Text(
          question.title,
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 18),
        Expanded(
          child: RadioGroup<String>(
            groupValue: _answers[question.answerKey(_currentIndex)],
            onChanged: (value) => setState(
              () => _answers[question.answerKey(_currentIndex)] = value ?? '',
            ),
            child: ListView.separated(
              itemCount: question.options.length,
              separatorBuilder: (context, index) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final option = question.options[index];
                return RadioListTile<String>(
                  value: question.optionCode(index),
                  title: Text('${question.optionCode(index)}. $option'),
                  tileColor: const Color(0xFF0F172A),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                );
              },
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildMonitorPanel() {
    return Column(
      children: [
        _CameraPreviewTile(
          title: 'Front camera',
          accent: Colors.cyanAccent,
          child: _buildFrontCameraPreview(),
        ),
        const SizedBox(height: 12),
        _CameraPreviewTile(
          title: 'Side camera',
          accent: _sideCameraStatus == 'ONLINE'
              ? Colors.greenAccent
              : Colors.cyanAccent,
          child: SideCameraStreamView(
            streamUrl: _sideCameraUrl,
            onConnected: (_) {
              if (mounted && _sideCameraStatus != 'ONLINE') {
                setState(() => _sideCameraStatus = 'ONLINE');
              }
            },
            onFailure: (reason) {
              if (mounted) {
                setState(() => _sideCameraStatus = 'STREAM_FAILED');
              }
              debugPrint('Side camera exam preview failed: $reason');
            },
          ),
        ),
        const SizedBox(height: 12),
        _SecureMonitoringPanel(
          connected: _connected,
          monitoringStarted: _monitoringStarted,
          sideCameraStatus: _sideCameraStatus,
          candidateStatus: _studentCandidateStatus,
          timeText: _timeText,
        ),
      ],
    );
  }

  String get _timeText {
    final minutes = (_remainingSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (_remainingSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
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

  bool get _sideCameraNeedsReconnect {
    return {
      'INVALID_IP',
      'STREAM_FAILED',
      'CAMERA_OFFLINE',
      'OFFLINE',
      'RECONNECTING',
      'RETRYING',
    }.contains(_sideCameraStatus);
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

  Widget _buildSideCameraOverlay() {
    return Positioned(
      left: 18,
      right: 18,
      bottom: 18,
      child: Material(
        elevation: 8,
        borderRadius: BorderRadius.circular(8),
        color: const Color(0xFF111827),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 10,
            children: [
              Icon(
                Icons.videocam_off,
                color: _sideCameraStatus == 'RECONNECTING'
                    ? Colors.orangeAccent
                    : Colors.redAccent,
              ),
              const Text(
                'Side camera connection required',
                style: TextStyle(fontWeight: FontWeight.w900),
              ),
              Text(
                _sideCameraStatus,
                style: const TextStyle(color: Colors.white60),
              ),
              OutlinedButton.icon(
                onPressed: _sideReconnectBusy ? null : _retrySideCamera,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
              FilledButton.icon(
                onPressed: _sideReconnectBusy ? null : _changeSideCameraIp,
                icon: _sideReconnectBusy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.edit),
                label: const Text('Re-enter IP'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _retrySideCamera() async {
    setState(() => _sideReconnectBusy = true);
    try {
      final result = await context.read<AppState>().api.checkSideCamera(
        _sessionId,
      );
      _handleRealtime(result);
      if (mounted && !_sideCameraNeedsReconnect && _cameraReady) {
        _startFrameUpload();
      }
    } catch (error, stackTrace) {
      debugPrint('Side camera retry failed: $error\n$stackTrace');
      if (mounted) setState(() => _sideCameraStatus = 'STREAM_FAILED');
    } finally {
      if (mounted) setState(() => _sideReconnectBusy = false);
    }
  }

  Future<void> _changeSideCameraIp() async {
    final controller = TextEditingController(text: _sideCameraUrl);
    final sideIp = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Reconnect Side Camera'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Camera URL or IP',
            hintText: 'http://192.168.0.5:8080/video',
            helperText:
                'Use an HTTP MJPEG stream such as http://PHONE_IP:8080/video. RTSP is not supported in Flutter Web.',
            prefixIcon: Icon(Icons.settings_input_antenna),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            icon: const Icon(Icons.refresh),
            label: const Text('Reconnect'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (sideIp == null || sideIp.isEmpty || !mounted) return;
    final streamInfo = resolveSideCameraStream(sideIp);
    debugPrint('Side camera reconnect attempted URL: ${streamInfo.url}');
    if (streamInfo.type == SideCameraStreamType.rtspUnsupported) {
      setState(() => _sideCameraStatus = 'STREAM_FAILED');
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'RTSP streams are not supported in Flutter Web. Use http://PHONE_IP:8080/video.',
          ),
        ),
      );
      return;
    }
    if (streamInfo.type == SideCameraStreamType.invalid) return;
    setState(() {
      _sideReconnectBusy = true;
      _sideCameraStatus = 'RETRYING';
    });
    final app = context.read<AppState>();
    try {
      final result = await app.api.reconnectSideCamera(
        sessionId: _sessionId,
        sideCameraUrl: streamInfo.url,
      );
      final success = result['success'] == true;
      setState(() {
        _sideCameraStatus =
            (result['state'] ?? (success ? 'ONLINE' : 'STREAM_FAILED'))
                .toString();
      });
      if (success) {
        final resolvedUrl = result['resolved_url']?.toString() ?? '';
        final usableUrl = resolvedUrl.isNotEmpty
            ? resolvedUrl
            : result['side_camera_url']?.toString() ?? streamInfo.url;
        await app.rememberSideCameraUrl(usableUrl);
        _sideCameraUrl = usableUrl;
        if (mounted && _cameraReady) _startFrameUpload();
      } else if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              result['message']?.toString() ??
                  'Unable to connect to side camera',
            ),
          ),
        );
      }
    } catch (error, stackTrace) {
      debugPrint('Side camera reconnect failed: $error\n$stackTrace');
      if (mounted) {
        setState(() => _sideCameraStatus = 'STREAM_FAILED');
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Unable to connect to side camera: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _sideReconnectBusy = false);
    }
  }
}

class _FeedPlaceholder extends StatelessWidget {
  const _FeedPlaceholder({
    required this.text,
    required this.loading,
    required this.onRetry,
  });

  final String text;
  final bool loading;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.black,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (loading)
                const SizedBox(
                  width: 26,
                  height: 26,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                const Icon(Icons.videocam_off, color: Colors.white38),
              const SizedBox(height: 12),
              Text(
                text,
                style: const TextStyle(color: Colors.white60),
                textAlign: TextAlign.center,
              ),
              if (!loading) ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Reconnect'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _CameraPreviewTile extends StatelessWidget {
  const _CameraPreviewTile({
    required this.title,
    required this.accent,
    required this.child,
  });

  final String title;
  final Color accent;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF070B16),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: accent.withValues(alpha: 0.45), width: 1.5),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Container(
            height: 36,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            color: const Color(0xFF0B1224),
            child: Row(
              children: [
                Icon(Icons.videocam, color: accent, size: 16),
                const SizedBox(width: 8),
                Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white70,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          AspectRatio(
            aspectRatio: 4 / 3,
            child: ColoredBox(color: Colors.black, child: child),
          ),
        ],
      ),
    );
  }
}

class _SecureMonitoringPanel extends StatelessWidget {
  const _SecureMonitoringPanel({
    required this.connected,
    required this.monitoringStarted,
    required this.sideCameraStatus,
    required this.candidateStatus,
    required this.timeText,
  });

  final bool connected;
  final bool monitoringStarted;
  final String sideCameraStatus;
  final String candidateStatus;
  final String timeText;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF08111F),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.cyanAccent.withValues(alpha: 0.28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Row(
            children: [
              Icon(Icons.radar, color: Colors.cyanAccent),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'AI Monitoring Active',
                  style: TextStyle(fontWeight: FontWeight.w900),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _StatusRow(
            label: 'Connection',
            value: connected ? 'Connected' : 'Reconnecting',
            color: connected ? Colors.greenAccent : Colors.orangeAccent,
          ),
          _StatusRow(
            label: 'Monitoring',
            value: monitoringStarted ? candidateStatus : 'STARTING',
            color: Colors.cyanAccent,
          ),
          _StatusRow(
            label: 'Side camera',
            value: sideCameraStatus,
            color: sideCameraStatus == 'ONLINE'
                ? Colors.greenAccent
                : Colors.orangeAccent,
          ),
          _StatusRow(label: 'Timer', value: timeText, color: Colors.redAccent),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
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
            style: TextStyle(color: color, fontWeight: FontWeight.w900),
          ),
        ],
      ),
    );
  }
}

class _WatermarkOverlay extends StatelessWidget {
  const _WatermarkOverlay({required this.studentName, required this.studentId});

  final String studentName;
  final String studentId;

  @override
  Widget build(BuildContext context) {
    final timestamp = DateTime.now().toIso8601String().substring(0, 16);
    final text = '$studentName | $studentId | $timestamp';
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = (constraints.maxWidth / 220).ceil().clamp(2, 6);
        final rows = (constraints.maxHeight / 120).ceil().clamp(2, 8);
        return GridView.builder(
          physics: const NeverScrollableScrollPhysics(),
          padding: const EdgeInsets.all(24),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            childAspectRatio: 2.6,
          ),
          itemCount: columns * rows,
          itemBuilder: (context, index) => Transform.rotate(
            angle: -0.45,
            child: Center(
              child: Text(
                text,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white24,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _Question {
  const _Question.text(this.title, this.options)
    : id = null,
      imageUrl = null,
      filename = null;

  const _Question.mcq({
    required this.id,
    required this.title,
    required this.options,
    this.imageUrl,
    this.filename,
  });

  const _Question.image({
    required this.id,
    required this.imageUrl,
    required this.filename,
  }) : title = '',
       options = const [];

  factory _Question.fromQuestionJson(
    Map<String, dynamic> json, {
    required String Function(int id) imageUrlForId,
  }) {
    final id = _readRequiredInt(json, 'id');
    final hasImage =
        _readString(json, 'image_url').isNotEmpty ||
        _readString(json, 'question_image').isNotEmpty;
    return _Question.mcq(
      id: id,
      title: _readString(json, 'question_text'),
      imageUrl: hasImage ? imageUrlForId(id) : null,
      filename: hasImage ? 'Question image' : null,
      options: [
        _readString(json, 'option_a'),
        _readString(json, 'option_b'),
        _readString(json, 'option_c'),
        _readString(json, 'option_d'),
      ],
    );
  }

  factory _Question.fromImageJson(
    Map<String, dynamic> json, {
    required String Function(int id) imageUrlForId,
  }) {
    final id = _readRequiredInt(json, 'id');
    return _Question.image(
      id: id,
      imageUrl: imageUrlForId(id),
      filename: json['original_filename']?.toString() ?? 'Question image',
    );
  }

  final String title;
  final List<String> options;
  final int? id;
  final String? imageUrl;
  final String? filename;

  bool get isImage => imageUrl != null;
  bool get isImageOnly => isImage && title.trim().isEmpty && options.isEmpty;

  String answerKey(int index) => id?.toString() ?? 'question_${index + 1}';

  String optionCode(int index) =>
      String.fromCharCode('A'.codeUnitAt(0) + index);

  static String _readString(Map<String, dynamic> json, String key) {
    return json[key]?.toString().trim() ?? '';
  }

  static int _readRequiredInt(Map<String, dynamic> json, String key) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value);
      if (parsed != null) return parsed;
    }
    throw FormatException('Question "$key" must be an integer.');
  }
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
