import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'api_service.dart';
import 'video_screen.dart';

class AdminPanel extends StatefulWidget {
  const AdminPanel({super.key});

  @override
  State<AdminPanel> createState() => _AdminPanelState();
}

class _AdminPanelState extends State<AdminPanel> with TickerProviderStateMixin {
  WebSocketChannel? channel;
  Timer? _reconnectTimer;

  // Stores sessions keyed by session_id
  final Map<String, Map<String, dynamic>> sessions = {};

  // Dashboard stats
  int totalActive = 0;
  int totalCheating = 0;
  int totalHighRisk = 0;

  @override
  void initState() {
    super.initState();
    _fetchInitialSessions();
    _connectWebSocket();
  }

  // ─────────────────────────────────────────────
  // FETCH INITIAL SESSION LIST (REST)
  // ─────────────────────────────────────────────
  Future<void> _fetchInitialSessions() async {
    final api = ApiService();
    try {
      final list = await api.getSessions();
      final stats = await api.getDashboardStats();

      if (mounted) {
        setState(() {
          for (final s in list) {
            sessions[s["session_id"]] = Map<String, dynamic>.from(s);
          }
          totalActive = stats["total_active"] ?? 0;
          totalCheating = stats["total_cheating"] ?? 0;
          totalHighRisk = stats["total_high_risk"] ?? 0;
        });
      }
    } catch (e) {
      debugPrint("Initial fetch error: $e");
    }
  }

  // ─────────────────────────────────────────────
  // WEBSOCKET — REAL-TIME UPDATES
  // ─────────────────────────────────────────────
  void _connectWebSocket() {
    try {
      channel = WebSocketChannel.connect(
        Uri.parse(ApiService.adminWebSocketUrl),
      );

      channel!.stream.listen(
        (data) {
          final decoded = jsonDecode(data);

          setState(() {
            sessions[decoded["session_id"]] = Map<String, dynamic>.from(decoded);
            _recalcStats();
          });
        },
        onError: (error) {
          debugPrint("WebSocket Error: $error");
          _scheduleReconnect();
        },
        onDone: () {
          debugPrint("WebSocket closed. Reconnecting...");
          _scheduleReconnect();
        },
      );
    } catch (e) {
      debugPrint("WebSocket connect error: $e");
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      if (mounted) _connectWebSocket();
    });
  }

  void _recalcStats() {
    totalActive = sessions.values.where((s) => s["is_active"] == true).length;
    totalCheating = sessions.values
        .where((s) => s["is_active"] == true && s["is_cheating"] == true)
        .length;
    totalHighRisk = sessions.values
        .where((s) =>
            s["is_active"] == true &&
            (s["risk_level"] == "HIGH" || s["risk_level"] == "CRITICAL"))
        .length;
  }

  @override
  void dispose() {
    channel?.sink.close();
    _reconnectTimer?.cancel();
    super.dispose();
  }

  // ─────────────────────────────────────────────
  // SORT: Cheating students → top, then by score
  // ─────────────────────────────────────────────
  List<MapEntry<String, Map<String, dynamic>>> _getSortedSessions() {
    final entries = sessions.entries.toList();

    entries.sort((a, b) {
      final aCheating = a.value["is_cheating"] == true ? 1 : 0;
      final bCheating = b.value["is_cheating"] == true ? 1 : 0;

      // Cheating students first
      if (aCheating != bCheating) return bCheating - aCheating;

      // Then by cheat_score descending
      final aScore = (a.value["cheat_score"] ?? 0.0) as num;
      final bScore = (b.value["cheat_score"] ?? 0.0) as num;
      if (aScore != bScore) return bScore.compareTo(aScore);

      // Then by cheat_count descending
      final aCount = (a.value["cheat_count"] ?? 0) as num;
      final bCount = (b.value["cheat_count"] ?? 0) as num;
      return bCount.compareTo(aCount);
    });

    return entries;
  }

  // ─────────────────────────────────────────────
  // BUILD
  // ─────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final sortedSessions = _getSortedSessions();

    return Scaffold(
      backgroundColor: const Color(0xFF0F0F1A),
      appBar: AppBar(
        title: const Text(
          "🔴 LIVE PROCTOR DASHBOARD",
          style: TextStyle(
            fontWeight: FontWeight.w800,
            letterSpacing: 1.2,
          ),
        ),
        backgroundColor: const Color(0xFF161627),
        foregroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _fetchInitialSessions,
            tooltip: "Refresh",
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => Navigator.pushReplacementNamed(context, '/'),
            tooltip: "Logout",
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Stats Bar ──
          _buildStatsBar(),

          // ── Session Grid ──
          Expanded(
            child: sortedSessions.isEmpty
                ? _buildEmptyState()
                : GridView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: sortedSessions.length,
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      crossAxisSpacing: 16,
                      mainAxisSpacing: 16,
                      childAspectRatio: 0.75,
                    ),
                    itemBuilder: (context, index) {
                      final entry = sortedSessions[index];
                      return _buildSessionCard(entry.key, entry.value);
                    },
                  ),
          ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────
  // STATS BAR
  // ─────────────────────────────────────────────
  Widget _buildStatsBar() {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF1E1E36), Color(0xFF252547)],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _statChip(Icons.people, "$totalActive", "Active", Colors.cyanAccent),
          _statChip(Icons.warning_amber_rounded, "$totalCheating", "Cheating",
              Colors.redAccent),
          _statChip(
              Icons.shield, "$totalHighRisk", "High Risk", Colors.orangeAccent),
        ],
      ),
    );
  }

  Widget _statChip(IconData icon, String value, String label, Color color) {
    return Column(
      children: [
        Row(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(width: 6),
            Text(
              value,
              style: TextStyle(
                color: color,
                fontSize: 22,
                fontWeight: FontWeight.w900,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: const TextStyle(color: Colors.white54, fontSize: 12),
        ),
      ],
    );
  }

  // ─────────────────────────────────────────────
  // EMPTY STATE
  // ─────────────────────────────────────────────
  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.monitor_heart_outlined,
              size: 64, color: Colors.white24),
          const SizedBox(height: 16),
          const Text(
            "Waiting for exam sessions...",
            style: TextStyle(
              fontSize: 18,
              color: Colors.white38,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            "Students will appear here when they start an exam",
            style: TextStyle(fontSize: 13, color: Colors.white24),
          ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────
  // SESSION CARD — with animated cheating glow
  // ─────────────────────────────────────────────
  Widget _buildSessionCard(String sessionId, Map<String, dynamic> session) {
    final isCheating = session["is_cheating"] ?? false;
    final riskLevel = session["risk_level"] ?? "LOW";
    final studentName = session["student_name"] ?? "Unknown";
    final studentId = session["student_id"] ?? sessionId;
    final examTitle = session["exam_title"] ?? "Exam";
    final cheatCount = session["cheat_count"] ?? 0;
    final cheatScore = (session["cheat_score"] ?? 0.0).toDouble();
    final cheatMessage = session["cheat_message"] ?? "Clear";
    final cheatType = session["cheat_type"] ?? "";

    // ── Determine colors based on state ──
    Color borderColor;
    Color glowColor;
    Color badgeColor;
    String statusText;
    IconData statusIcon;

    if (isCheating) {
      borderColor = Colors.red;
      glowColor = Colors.red.withValues(alpha: 0.5);
      badgeColor = Colors.red;
      statusText = "⚠ CHEATING";
      statusIcon = Icons.warning_rounded;
    } else if (riskLevel == "HIGH" || riskLevel == "CRITICAL") {
      borderColor = Colors.orange;
      glowColor = Colors.orange.withValues(alpha: 0.3);
      badgeColor = Colors.orange;
      statusText = "⚡ HIGH RISK";
      statusIcon = Icons.shield;
    } else if (riskLevel == "MEDIUM") {
      borderColor = Colors.amber;
      glowColor = Colors.transparent;
      badgeColor = Colors.amber;
      statusText = "● MEDIUM";
      statusIcon = Icons.info_outline;
    } else {
      borderColor = Colors.green;
      glowColor = Colors.transparent;
      badgeColor = Colors.green;
      statusText = "✓ CLEAR";
      statusIcon = Icons.verified;
    }

    return GestureDetector(
      onTap: () {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => VideoScreen(sessionId: sessionId),
          ),
        );
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 400),
        curve: Curves.easeInOut,
        decoration: BoxDecoration(
          color: const Color(0xFF1A1A2E),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: borderColor,
            width: isCheating ? 3.0 : 2.0,
          ),
          boxShadow: [
            if (isCheating)
              BoxShadow(
                color: glowColor,
                blurRadius: 20,
                spreadRadius: 4,
              ),
            if (riskLevel == "HIGH" || riskLevel == "CRITICAL")
              BoxShadow(
                color: glowColor,
                blurRadius: 14,
                spreadRadius: 2,
              ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Top badge ──
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: badgeColor.withValues(alpha: 0.15),
                borderRadius: const BorderRadius.vertical(
                  top: Radius.circular(14),
                ),
              ),
              child: Row(
                children: [
                  Icon(statusIcon, color: badgeColor, size: 18),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      statusText,
                      style: TextStyle(
                        color: badgeColor,
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ),
                  if (cheatCount > 0)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.red.withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        "$cheatCount",
                        style: const TextStyle(
                          color: Colors.redAccent,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                ],
              ),
            ),

            // ── Center icon area ──
            Expanded(
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    // Animated cheating indicator
                    isCheating
                        ? _CheatingPulse(color: borderColor)
                        : Icon(
                            Icons.person,
                            color: borderColor.withValues(alpha: 0.6),
                            size: 48,
                          ),
                    const SizedBox(height: 8),
                    // Student name
                    Text(
                      studentName,
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 15,
                      ),
                      textAlign: TextAlign.center,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      "ID: $studentId",
                      style: const TextStyle(
                        color: Colors.white38,
                        fontSize: 11,
                      ),
                    ),
                    if (isCheating && cheatType.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: Colors.red.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                              color: Colors.red.withValues(alpha: 0.3)),
                        ),
                        child: Text(
                          cheatType,
                          style: const TextStyle(
                            color: Colors.redAccent,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 1,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),

            // ── Bottom info bar ──
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: borderColor.withValues(alpha: 0.12),
                borderRadius: const BorderRadius.vertical(
                  bottom: Radius.circular(14),
                ),
              ),
              child: Column(
                children: [
                  Text(
                    examTitle,
                    style: const TextStyle(
                      color: Colors.white70,
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        cheatMessage,
                        style: TextStyle(
                          color: isCheating ? Colors.redAccent : Colors.white38,
                          fontSize: 11,
                          fontWeight: isCheating
                              ? FontWeight.bold
                              : FontWeight.normal,
                        ),
                      ),
                      Text(
                        "Score: ${cheatScore.toStringAsFixed(0)}",
                        style: TextStyle(
                          color: cheatScore > 100
                              ? Colors.orangeAccent
                              : Colors.white30,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}


// ─────────────────────────────────────────────
// ANIMATED PULSING ICON FOR CHEATING STUDENTS
// ─────────────────────────────────────────────
class _CheatingPulse extends StatefulWidget {
  final Color color;
  const _CheatingPulse({required this.color});

  @override
  State<_CheatingPulse> createState() => _CheatingPulseState();
}

class _CheatingPulseState extends State<_CheatingPulse>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat(reverse: true);

    _animation = Tween<double>(begin: 0.7, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, child) {
        return Transform.scale(
          scale: _animation.value,
          child: Icon(
            Icons.warning_rounded,
            color: widget.color,
            size: 52,
          ),
        );
      },
    );
  }
}