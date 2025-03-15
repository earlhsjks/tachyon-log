document.addEventListener("DOMContentLoaded", function () {
    function updateClock() {
        let now = new Date();

        // Format Date
        let dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        document.getElementById("date").innerText = now.toLocaleDateString('en-US', dateOptions);

        // Format Time
        let hours = now.getHours();
        let minutes = now.getMinutes();
        let seconds = now.getSeconds();
        let ampm = hours >= 12 ? 'PM' : 'AM';
        
        hours = hours % 12 || 12; // Convert 24hr to 12hr format
        minutes = minutes < 10 ? '0' + minutes : minutes;
        seconds = seconds < 10 ? '0' + seconds : seconds;

        document.getElementById("clock").innerText = `${hours}:${minutes}:${seconds} ${ampm}`;
    }

    // Update Clock Every Second
    setInterval(updateClock, 1000);
    updateClock(); // Initialize immediately
});
