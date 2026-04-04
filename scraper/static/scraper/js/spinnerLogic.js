document.addEventListener('DOMContentLoaded', function () {

    // Playlist Selection Toggling Logic
    const select = document.getElementById('playlistAction');
    const input = document.getElementById('newPlaylistInput');

    if (select && input) {
        select.addEventListener('change', function () {
            if (this.value === 'new') {
                input.style.display = 'block';
                input.required = true;
            } else {
                input.style.display = 'none';
                input.required = false;
            }
        });
    }

    // spinner logic
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