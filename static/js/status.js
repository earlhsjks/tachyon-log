document.addEventListener("DOMContentLoaded", function () {
    function updateClock() {
        let now = new Date();

        let dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        document.getElementById("clock").innerText = now.toLocaleDateString('en-US', dateOptions);

        let hours = now.getHours();
        let minutes = now.getMinutes();
        let seconds = now.getSeconds();
        let ampm = hours >= 12 ? 'PM' : 'AM';

        hours = hours % 12 || 12;
        minutes = minutes < 10 ? '0' + minutes : minutes;
        seconds = seconds < 10 ? '0' + seconds : seconds;

        document.getElementById("clock").innerText = `${hours}:${minutes}:${seconds} ${ampm}`;
    }

    // Blinking effect for the status icon
    let statusIcon = document.getElementById("status-icon");
    if (statusIcon) {
        statusIcon.classList.add("blink");
    }

    setInterval(updateClock, 1000);
    updateClock();
});
