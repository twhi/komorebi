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
});