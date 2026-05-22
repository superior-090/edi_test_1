import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'api_config.dart';
import 'design_system.dart';
import 'exam_screen.dart';
import 'side_camera_stream.dart';

class StudentPanel extends StatefulWidget {
  const StudentPanel({super.key});

  @override
  State<StudentPanel> createState() => _StudentPanelState();
}

class _StudentPanelState extends State<StudentPanel> {
  final _sideCameraController = TextEditingController();
  Timer? _examRefreshTimer;
  bool _prefilledSideCamera = false;
  bool _loadingExams = true;
  List<Map<String, dynamic>> _exams = [];

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_prefilledSideCamera) {
      _sideCameraController.text = context.read<AppState>().sideCameraUrl;
      _prefilledSideCamera = true;
      _loadExams();
      _examRefreshTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => _loadExams(showLoading: false),
      );
    }
  }

  Future<void> _loadExams({bool showLoading = true}) async {
    final app = context.read<AppState>();
    if (showLoading) setState(() => _loadingExams = true);
    try {
      final rows = await app.api.getAvailableExams();
      debugPrint('[Student] fetched ${rows.length} active exams');
      if (!mounted) return;
      setState(() {
        _exams = rows
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Exam list unavailable: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingExams = false);
    }
  }

  @override
  void dispose() {
    _examRefreshTimer?.cancel();
    _sideCameraController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Candidate Command Center'),
        actions: [
          const Padding(
            padding: EdgeInsets.only(right: 8),
            child: Center(
              child: StatusBadge(
                label: 'Ready',
                color: AiColors.green,
                pulse: true,
              ),
            ),
          ),
          Center(
            child: Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                app.displayName,
                style: const TextStyle(color: Colors.white70),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Logout',
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await context.read<AppState>().logout();
              if (context.mounted) {
                Navigator.pushReplacementNamed(context, '/login');
              }
            },
          ),
        ],
      ),
      body: AiGradientBackground(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 980;
            return ListView(
              padding: const EdgeInsets.all(18),
              children: [
                _CandidateHero(name: app.displayName, exams: _exams.length),
                if (!app.isProfileComplete) ...[
                  const SizedBox(height: 12),
                  _ProfileRequiredPanel(
                    onComplete: () =>
                        Navigator.pushReplacementNamed(context, '/profile'),
                  ),
                ],
                const SizedBox(height: 16),
                if (wide)
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 3, child: _buildExamList()),
                      const SizedBox(width: 14),
                      const SizedBox(width: 330, child: _CandidateSidePanel()),
                    ],
                  )
                else ...[
                  _buildExamList(),
                  const SizedBox(height: 14),
                  const _CandidateSidePanel(),
                ],
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildExamList() {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionTitle(
            title: 'Available Exams',
            subtitle: 'All active published assessments',
            action: IconButton.filledTonal(
              tooltip: 'Refresh exams',
              onPressed: _loadExams,
              icon: const Icon(Icons.refresh),
            ),
          ),
          const SizedBox(height: 14),
          if (_loadingExams)
            const SizedBox(
              height: 180,
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_exams.isEmpty)
            const _EmptyExamState()
          else
            ..._exams.map(
              (exam) => _ExamCard(
                exam: exam,
                sideCameraController: _sideCameraController,
              ),
            ),
        ],
      ),
    );
  }
}

class _ProfileRequiredPanel extends StatelessWidget {
  const _ProfileRequiredPanel({required this.onComplete});

  final VoidCallback onComplete;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.orangeAccent.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.orangeAccent.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.badge, color: Colors.orangeAccent),
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              'Add your profile details for reports and identity records.',
            ),
          ),
          GradientButton(
            onPressed: onComplete,
            icon: Icons.edit,
            label: 'Complete',
          ),
        ],
      ),
    );
  }
}

class _EmptyExamState extends StatelessWidget {
  const _EmptyExamState();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(34),
      child: const Center(
        child: Text(
          'No active exams available',
          style: TextStyle(color: Colors.white60),
        ),
      ),
    );
  }
}

class _CandidateHero extends StatelessWidget {
  const _CandidateHero({required this.name, required this.exams});

  final String name;
  final int exams;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(18),
      borderColor: AiColors.cyan.withValues(alpha: 0.25),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final narrow = constraints.maxWidth < 780;
          final intro = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const StatusBadge(
                label: 'Identity verified',
                color: AiColors.cyan,
                icon: Icons.verified_user,
              ),
              const SizedBox(height: 12),
              Text(
                'Welcome, $name',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Camera readiness, exam status, and monitoring requirements are prepared before launch.',
                style: TextStyle(color: Colors.white70),
              ),
            ],
          );
          final metrics = Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              SizedBox(
                width: narrow ? constraints.maxWidth : 180,
                child: MetricTile(
                  icon: Icons.assignment_turned_in,
                  label: 'Exams',
                  value: '$exams',
                  caption: 'available now',
                  color: AiColors.purple,
                ),
              ),
              SizedBox(
                width: narrow ? constraints.maxWidth : 180,
                child: const MetricTile(
                  icon: Icons.videocam,
                  label: 'Monitoring',
                  value: 'Dual',
                  caption: 'front + side',
                  color: AiColors.cyan,
                ),
              ),
              SizedBox(
                width: narrow ? constraints.maxWidth : 180,
                child: const MetricTile(
                  icon: Icons.shield,
                  label: 'Integrity',
                  value: 'Active',
                  caption: 'copy guard',
                  color: AiColors.green,
                ),
              ),
            ],
          );
          return narrow
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [intro, const SizedBox(height: 14), metrics],
                )
              : Row(
                  children: [
                    Expanded(child: intro),
                    const SizedBox(width: 18),
                    metrics,
                  ],
                );
        },
      ),
    );
  }
}

class _CandidateSidePanel extends StatelessWidget {
  const _CandidateSidePanel();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Readiness Matrix',
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 12),
          const StatusBadge(
            label: 'Side camera required',
            color: AiColors.amber,
            icon: Icons.settings_input_antenna,
          ),
          const SizedBox(height: 10),
          const StatusBadge(
            label: 'Fullscreen recommended',
            color: AiColors.cyan,
            icon: Icons.fullscreen,
          ),
          const SizedBox(height: 10),
          const StatusBadge(
            label: 'Tab switch logged',
            color: AiColors.red,
            icon: Icons.warning_amber,
          ),
          const SizedBox(height: 18),
          const SizedBox(
            height: 130,
            child: MiniBars(
              values: [0.2, 0.36, 0.28, 0.5, 0.42, 0.72, 0.58, 0.85],
              color: AiColors.purple,
            ),
          ),
        ],
      ),
    );
  }
}

class _SideCameraTestResult {
  const _SideCameraTestResult({required this.url});

  final String url;
}

class _ExamCard extends StatefulWidget {
  const _ExamCard({required this.exam, required this.sideCameraController});

  final Map<String, dynamic> exam;
  final TextEditingController sideCameraController;

  @override
  State<_ExamCard> createState() => _ExamCardState();
}

class _ExamCardState extends State<_ExamCard> {
  bool sideCamConnected = false;
  String? _successfulSideCameraUrl;

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    final subjectName = _text('subject_name', fallback: _text('subject'));
    final teacherName = _text('teacher_name', fallback: 'Faculty');
    final duration = (widget.exam['duration_minutes'] as num?)?.toInt() ?? 60;
    final marks = widget.exam['total_marks']?.toString() ?? '-';
    final questionCount = widget.exam['question_count']?.toString() ?? '0';
    final schedule = _formatSchedule(
      widget.exam['start_time'],
      widget.exam['end_time'],
    );
    return GlassCard(
      padding: EdgeInsets.zero,
      borderColor: AiColors.cyan.withValues(alpha: 0.14),
      onTap: () => _startExam(context, app),
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Container(
              width: 54,
              height: 54,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AiColors.cyan, AiColors.blue],
                ),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Center(
                child: Text(
                  (widget.exam['subject'] ?? '-').toString(),
                  style: const TextStyle(
                    color: Color(0xFF07111A),
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    widget.exam['title'].toString(),
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subjectName,
                    style: const TextStyle(color: Colors.white70),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '$teacherName - $duration min - $marks marks - $questionCount questions',
                    style: const TextStyle(color: Colors.white60),
                  ),
                  const SizedBox(height: 4),
                  Text(schedule, style: const TextStyle(color: Colors.white60)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: const [
                      StatusBadge(
                        label: 'Published',
                        color: AiColors.green,
                        icon: Icons.check_circle,
                      ),
                      StatusBadge(
                        label: 'AI monitored',
                        color: AiColors.cyan,
                        icon: Icons.radar,
                      ),
                    ],
                  ),
                ],
              ),
            ),
            GradientButton(
              onPressed: () => _startExam(context, app),
              icon: Icons.play_arrow,
              label: 'Start',
            ),
          ],
        ),
      ),
    );
  }

  String _text(String key, {String fallback = ''}) {
    final value = widget.exam[key]?.toString().trim() ?? '';
    return value.isEmpty ? fallback : value;
  }

  String _formatSchedule(dynamic start, dynamic end) {
    final startText = _shortDate(start);
    final endText = _shortDate(end);
    if (startText.isEmpty && endText.isEmpty) return 'Open schedule';
    if (startText.isEmpty) return 'Open until $endText';
    if (endText.isEmpty) return 'Starts $startText';
    return '$startText to $endText';
  }

  String _shortDate(dynamic value) {
    final text = value?.toString() ?? '';
    if (text.isEmpty) return '';
    final cleaned = text.replaceFirst('T', ' ');
    return cleaned.length > 16 ? cleaned.substring(0, 16) : cleaned;
  }

  Future<void> _startExam(BuildContext context, AppState app) async {
    final testResult = await _showSideCameraInput(context);
    if (testResult == null || !mounted) return;

    final backendReady = await _backendWorks(app);
    if (!backendReady) {
      if (!mounted) return;
      ScaffoldMessenger.of(this.context).showSnackBar(
        SnackBar(
          content: Text(
            'Backend unavailable at ${ApiConfig.baseUrl}. Start the backend, then try again.',
          ),
        ),
      );
      return;
    }

    final frontCamWorks = await _frontCameraWorks();
    if (!frontCamWorks || !sideCamConnected) {
      if (!mounted) return;
      ScaffoldMessenger.of(this.context).showSnackBar(
        const SnackBar(
          content: Text('Front camera and side camera test must pass first.'),
        ),
      );
      return;
    }

    await app.rememberSideCameraUrl(testResult.url);
    if (!mounted) return;
    Navigator.push(
      this.context,
      MaterialPageRoute(
        builder: (_) => ExamScreen(
          examTitle: widget.exam['title'].toString(),
          examId: (widget.exam['id'] as num?)?.toInt(),
          subject: widget.exam['subject'].toString(),
          durationMinutes:
              (widget.exam['duration_minutes'] as num?)?.toInt() ?? 60,
          sideCameraUrl: testResult.url,
          studentId: app.username,
          studentName: app.displayName,
        ),
      ),
    );
  }

  Future<bool> _backendWorks(AppState app) async {
    try {
      final health = await app.api.health();
      debugPrint('Backend health OK: $health');
      return true;
    } catch (error, stackTrace) {
      debugPrint('Backend health failed: $error\n$stackTrace');
      return false;
    }
  }

  Future<bool> _frontCameraWorks() async {
    try {
      final cameras = await availableCameras();
      final works = cameras.isNotEmpty;
      debugPrint('Front camera preflight: ${works ? 'available' : 'missing'}');
      return works;
    } catch (error, stackTrace) {
      debugPrint('Front camera preflight failed: $error\n$stackTrace');
      return false;
    }
  }

  Future<_SideCameraTestResult?> _showSideCameraInput(BuildContext context) {
    sideCamConnected = false;
    _successfulSideCameraUrl = null;
    return showDialog<_SideCameraTestResult>(
      context: context,
      barrierDismissible: false,
      builder: (context) {
        String? testUrl;
        String status = 'Stream unavailable';
        bool testing = false;
        bool connected = false;
        return StatefulBuilder(
          builder: (context, setDialogState) {
            void testStream() {
              final info = resolveSideCameraStream(
                widget.sideCameraController.text,
              );
              debugPrint('Side camera test attempted URL: ${info.url}');
              setDialogState(() {
                testUrl = info.url;
                testing = info.type == SideCameraStreamType.mjpeg;
                connected = false;
                status = info.type == SideCameraStreamType.rtspUnsupported
                    ? 'RTSP is unsupported on Flutter Web'
                    : 'Connecting to side camera...';
              });
              sideCamConnected = false;
              _successfulSideCameraUrl = null;
            }

            return AlertDialog(
              title: Text('Start ${widget.exam['title']}'),
              content: SizedBox(
                width: 560,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextField(
                      controller: widget.sideCameraController,
                      autofocus: true,
                      decoration: const InputDecoration(
                        labelText: 'Camera URL or IP',
                        hintText: 'http://192.168.0.5:8080/video',
                        helperText:
                            'Use the HTTP MJPEG stream from IP Webcam. RTSP is not supported in Flutter Web.',
                        prefixIcon: Icon(Icons.settings_input_antenna),
                      ),
                      onChanged: (_) {
                        setDialogState(() {
                          testUrl = null;
                          testing = false;
                          connected = false;
                          status = 'Stream unavailable';
                        });
                        sideCamConnected = false;
                        _successfulSideCameraUrl = null;
                      },
                    ),
                    const SizedBox(height: 12),
                    AspectRatio(
                      aspectRatio: 16 / 9,
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: testUrl == null
                            ? const ColoredBox(
                                color: Colors.black,
                                child: Center(
                                  child: Text(
                                    'Test Stream before starting the exam',
                                    style: TextStyle(color: Colors.white70),
                                  ),
                                ),
                              )
                            : SideCameraStreamView(
                                key: ValueKey(testUrl),
                                streamUrl: testUrl!,
                                onConnected: (url) {
                                  sideCamConnected = true;
                                  _successfulSideCameraUrl = url;
                                  setDialogState(() {
                                    connected = true;
                                    testing = false;
                                    status = 'Connected';
                                  });
                                },
                                onFailure: (reason) {
                                  sideCamConnected = false;
                                  _successfulSideCameraUrl = null;
                                  setDialogState(() {
                                    connected = false;
                                    testing = false;
                                    status = 'Stream unavailable';
                                  });
                                },
                              ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      status,
                      style: TextStyle(
                        color: connected
                            ? Colors.greenAccent
                            : testing
                            ? Colors.orangeAccent
                            : Colors.white70,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    if (testUrl != null)
                      Text(
                        'Attempted URL: $testUrl',
                        style: const TextStyle(
                          color: Colors.white60,
                          fontSize: 12,
                        ),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Cancel'),
                ),
                OutlinedButton.icon(
                  onPressed: testStream,
                  icon: const Icon(Icons.network_check),
                  label: const Text('Test Stream'),
                ),
                FilledButton.icon(
                  onPressed: connected && _successfulSideCameraUrl != null
                      ? () => Navigator.pop(
                          context,
                          _SideCameraTestResult(
                            url: _successfulSideCameraUrl!,
                          ),
                        )
                      : null,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Start Exam'),
                ),
              ],
            );
          },
        );
      },
    );
  }

}
