document.addEventListener("DOMContentLoaded", function () {
    let offset = 0; // Time offset in milliseconds

    async function syncTime() {
        try {
            let response = await fetch("https://worldtimeapi.org/api/timezone/Asia/Singapore");
            if (!response.ok) throw new Error("Failed to fetch time");

            let data = await response.json();
            let serverTime = new Date(data.datetime).getTime();
            let localTime = new Date().getTime();

            // Calculate the offset (Server Time - Local Time)
            offset = serverTime - localTime;
            console.log("Time synced with internet:", new Date(serverTime));
        } catch (error) {
            console.warn("Failed to sync time with internet. Using local time.");
        }
    }

    function updateClock() {
        let now = new Date(new Date().getTime() + offset); // Apply offset

        // Format Date
        let dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        document.getElementById("date").innerText = now.toLocaleDateString('en-US', dateOptions);

        // Format Time
        let hours = now.getHours();
        let minutes = now.getMinutes();
        let seconds = now.getSeconds();
        let ampm = hours >= 12 ? 'PM' : 'AM';
        
        hours = hours % 12 || 12; // Convert 24hr to 12hr format
        minutes = minutes.toString().padStart(2, '0');
        seconds = seconds.toString().padStart(2, '0');

        document.getElementById("clock").innerText = `${hours}:${minutes}:${seconds} ${ampm}`;
    }

    // Sync time every 1 minute
    syncTime();
    setInterval(syncTime, 60000);

    // Update clock every second
    setInterval(updateClock, 1000);
    updateClock();

    // Blinking effect for status icon
    let statusIcon = document.getElementById("status-icon");
    if (statusIcon) {
        statusIcon.classList.add("blink");
    }
});
