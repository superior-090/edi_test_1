import 'package:flutter/material.dart';
import 'exam_screen.dart';

class StudentPanel extends StatelessWidget {
  const StudentPanel({super.key});

  // Mock Data for Exams
  final List<Map<String, String>> exams = const [
    {'title': 'Computer Science 101', 'duration': '60 min', 'subject': 'CS'},
    {'title': 'Digital Marketing', 'duration': '30 min', 'subject': 'Business'},
    {'title': 'AI & Ethics', 'duration': '45 min', 'subject': 'Philosophy'},
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Available Exams"),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => Navigator.pushReplacementNamed(context, '/'),
          )
        ],
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: exams.length,
        itemBuilder: (context, index) {
          final exam = exams[index];
          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            child: ListTile(
              leading: CircleAvatar(child: Text(exam['subject']![0])),
              title: Text(exam['title']!),
              subtitle: Text("Time limit: ${exam['duration']}"),
              trailing: ElevatedButton(
                onPressed: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (context) => ExamScreen(examTitle: exam['title']!),
                    ),
                  );
                },
                child: const Text("Start"),
              ),
            ),
          );
        },
      ),
    );
  }
}