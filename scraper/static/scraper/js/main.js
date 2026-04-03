document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('scrapeForm');
    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const btnSpinner = document.getElementById('btnSpinner');

    if (form) {
        form.addEventListener('submit', function () {
            submitBtn.disabled = true;
            submitBtn.classList.add('opacity-50', 'cursor-not-allowed');

            btnText.textContent = 'Processing...';
            btnSpinner.classList.remove('hidden');
        });
    }
});