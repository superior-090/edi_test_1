import 'package:flutter/material.dart';

class AdminPanel extends StatelessWidget {
  const AdminPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Proctoring Logs")),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _statusCard("Active Sessions", "24", Colors.blue),
                const SizedBox(width: 12),
                _statusCard("Alerts", "05", Colors.redAccent),
              ],
            ),
            const SizedBox(height: 32),
            const Text(
                "Live Violation Feed",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)
            ),
            const SizedBox(height: 12),
            Expanded(
              child: ListView.separated(
                itemCount: 5,
                separatorBuilder: (context, index) => const Divider(),
                itemBuilder: (context, index) => ListTile(
                  leading: const Icon(Icons.warning_amber_rounded, color: Colors.orange),
                  title: Text("User ID: STUD_00${index + 101}"),
                  subtitle: const Text("Potential object detected: Smartphone"),
                  trailing: TextButton(
                    onPressed: () {},
                    child: const Text("View Snapshot"),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusCard(String title, String count, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withOpacity(0.5)),
        ),
        child: Column(
          children: [
            Text(
                count,
                style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: color
                )
            ),
            Text(title, style: TextStyle(color: color.withOpacity(0.8))),
          ],
        ),
      ),
    );
  }
}