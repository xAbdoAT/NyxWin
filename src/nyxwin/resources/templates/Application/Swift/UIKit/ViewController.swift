import UIKit

class ViewController: UIViewController {
    private var tapCount = 0
    private let countLabel = UILabel()

    override func viewDidLoad() {
        super.viewDidLoad()

        view.backgroundColor = .systemBackground

        let symbolConfig = UIImage.SymbolConfiguration(pointSize: 48, weight: .semibold)
        let imageView = UIImageView(image: UIImage(systemName: "app.badge.checkmark", withConfiguration: symbolConfig))
        imageView.tintColor = .systemBlue
        imageView.contentMode = .scaleAspectFit

        let titleLabel = UILabel()
        titleLabel.text = "__APP_NAME__"
        titleLabel.font = .systemFont(ofSize: 24, weight: .bold)
        titleLabel.textAlignment = .center
        titleLabel.textColor = .label

        let subtitleLabel = UILabel()
        subtitleLabel.text = "NyxWin UIKit application compiled natively on Windows."
        subtitleLabel.font = .systemFont(ofSize: 15, weight: .regular)
        subtitleLabel.textAlignment = .center
        subtitleLabel.textColor = .secondaryLabel
        subtitleLabel.numberOfLines = 0

        countLabel.text = "Interactive Test: 0 taps"
        countLabel.font = .monospacedDigitSystemFont(ofSize: 17, weight: .medium)
        countLabel.textAlignment = .center
        countLabel.textColor = .systemIndigo

        let button = UIButton(type: .system)
        button.setTitle("Tap to Verify UI Response", for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 16, weight: .semibold)
        button.backgroundColor = .systemBlue
        button.setTitleColor(.white, for: .normal)
        button.layer.cornerRadius = 10
        button.addTarget(self, action: #selector(handleButtonTap), for: .touchUpInside)

        let stackView = UIStackView(arrangedSubviews: [
            imageView,
            titleLabel,
            subtitleLabel,
            countLabel,
            button
        ])
        stackView.axis = .vertical
        stackView.spacing = 16
        stackView.alignment = .center
        stackView.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(stackView)

        NSLayoutConstraint.activate([
            stackView.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            stackView.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            stackView.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 24),
            stackView.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -24),
            button.heightAnchor.constraint(equalToConstant: 44),
            button.widthAnchor.constraint(greaterThanOrEqualToConstant: 200)
        ])
    }

    @objc private func handleButtonTap() {
        tapCount += 1
        countLabel.text = "Interactive Test: \(tapCount) tap\(tapCount == 1 ? "" : "s")"

        UIView.animate(withDuration: 0.12, animations: {
            self.countLabel.transform = CGAffineTransform(scaleX: 1.15, y: 1.15)
        }) { _ in
            UIView.animate(withDuration: 0.12) {
                self.countLabel.transform = .identity
            }
        }
    }
}
