document.addEventListener("DOMContentLoaded", function () {
    // Attach event listeners to all delete buttons
    document.querySelectorAll(".delete-btn").forEach((button) => {
        button.addEventListener("click", function (event) {
            event.preventDefault(); // Prevent form submission
            
            // Get employee name
            const employeeName = this.closest("tr").querySelector("td:nth-child(2)").innerText;
            
            // Show confirmation modal
            showDeleteConfirmation(employeeName, this.closest("form"));
        });
    });
});

// Function to show the confirmation modal
function showDeleteConfirmation(employeeName, form) {
    const modal = document.getElementById("confirmation-modal");
    const modalText = document.getElementById("modal-text");
    const confirmButton = document.getElementById("confirm-delete");
    
    modalText.innerText = `Are you sure you want to delete ${employeeName}?`;
    
    // Show modal
    modal.classList.add("show");

    // If user confirms, submit form
    confirmButton.onclick = function () {
        form.submit();
        modal.classList.remove("show");
    };

    // Close modal on cancel
    document.getElementById("cancel-delete").onclick = function () {
        modal.classList.remove("show");
    };
}
