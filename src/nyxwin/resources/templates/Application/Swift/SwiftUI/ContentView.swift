import SwiftUI

struct ContentView: View {
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "swift")
                    .font(.system(size: 60))
                    .foregroundStyle(.tint)

                VStack(spacing: 8) {
                    Text("Hello, iOS!")
                        .font(.title2)
                        .fontWeight(.bold)

                    Text("Native Swift application compiled on Windows.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
            }
            .padding()
            .navigationTitle("__APP_NAME__")
        }
    }
}
