// Global variables
let currentTicketId = null;
let currentExecutionData = null;

// Submit issue form
async function submitIssue(event) {
    event.preventDefault();
    
    const form = document.getElementById('issueForm');
    const submitButton = form.querySelector('button[type="submit"]');
    const description = document.getElementById('issueDescription').value;
    const responseArea = document.getElementById('responseArea');
    const responseContent = document.getElementById('responseContent');
    
    try {
        // Disable submit button and show loading state
        submitButton.disabled = true;
        submitButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processing...';
        
        // Submit the issue
        const response = await fetch('/submit_issue', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `issue_description=${encodeURIComponent(description)}`
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showResponse(result);
            form.reset();
        } else {
            showError(result.error || 'Unknown error occurred');
        }
    } catch (error) {
        console.error('Error submitting issue:', error);
        showError(`Failed to submit issue: ${error.message}`);
    } finally {
        // Reset submit button
        submitButton.disabled = false;
        submitButton.innerHTML = '<i class="fas fa-paper-plane me-2"></i>Submit';
    }
}

// Display response in the UI
function showResponse(result) {
    const responseArea = document.getElementById('responseArea');
    const responseContent = document.getElementById('responseContent');
    const executionApproval = document.getElementById('executionApproval');
    
    responseArea.classList.remove('d-none');
    
    let content = '';
    
    switch (result.type) {
        case 'infrastructure_query':
            content = formatInfrastructureResponse(result);
            break;
        case 'knowledge_query':
            content = formatKnowledgeResponse(result.data);
            break;
        case 'api_query':
            content = formatApiResponse(result.data);
            break;
        case 'resolution':
            content = formatResolutionResponse(result.data);
            break;
        default:
            content = `<div class="alert alert-warning">Unsupported response type: ${result.type}</div>`;
    }
    
    responseContent.innerHTML = content;
    
    // Handle execution approval if needed
    if (result.type === 'resolution' && result.data.validation?.approved) {
        executionApproval.classList.remove('d-none');
        currentTicketId = result.data.ticketId;
        currentExecutionData = result.data.execution;
    } else {
        executionApproval.classList.add('d-none');
    }
    
    // Scroll to response
    responseArea.scrollIntoView({ behavior: 'smooth' });
}

// Format infrastructure query response
function formatInfrastructureResponse(result) {
    let html = '<div class="infrastructure-results">';
    
    // Handle infrastructure overview
    if (result.type === 'infrastructure_overview') {
        const overview = result.overview;
        
        html += `
            <div class="card mb-3">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0">Infrastructure Overview</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6><i class="fas fa-server me-2"></i>Servers (${overview.total_servers})</h6>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead>
                                        <tr>
                                            <th>Server</th>
                                            <th>IP</th>
                                            <th>OS</th>
                                            <th>Services</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${Object.entries(overview.servers).map(([name, info]) => `
                                            <tr>
                                                <td>${name}</td>
                                                <td><code>${info.ip}</code></td>
                                                <td>${info.os}</td>
                                                <td>${info.services.join(', ')}</td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <h6><i class="fas fa-cogs me-2"></i>Services Distribution</h6>
                            <div class="list-group">
                                ${Object.entries(overview.services_summary).map(([service, servers]) => `
                                    <div class="list-group-item">
                                        <div class="d-flex justify-content-between align-items-center">
                                            <strong>${service}</strong>
                                            <span class="badge bg-primary rounded-pill">${servers.length} servers</span>
                                        </div>
                                        <small class="text-muted">Running on: ${servers.join(', ')}</small>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        return html;
    }
    
    // Show any errors at the top
    if (result.errors && result.errors.length > 0) {
        html += '<div class="alert alert-warning mb-3"><h6>Warnings:</h6><ul class="mb-0">';
        result.errors.forEach(error => {
            html += `<li>${error}</li>`;
        });
        html += '</ul></div>';
    }
    
    // Show results for each server
    if (result.results && Object.keys(result.results).length > 0) {
        for (const [server, info] of Object.entries(result.results)) {
            html += `
                <div class="card mb-3">
                    <div class="card-header">
                        <h6 class="mb-0">
                            <i class="fas fa-server me-2"></i>${server}
                            <small class="text-muted">(${info.ip})</small>
                        </h6>
                    </div>
                    <div class="card-body">
                        <h6>Services: ${info.services.join(', ')}</h6>
                        <hr>
                        <div class="command-outputs">
                `;
                
                const commands = info.commands.commands || [];
                if (commands.length > 0) {
                    commands.forEach(cmd => {
                        const statusClass = cmd.success ? 'text-success' : 'text-danger';
                        const statusIcon = cmd.success ? 'check-circle' : 'times-circle';
                        html += `
                            <div class="command-output mb-3">
                                <div class="d-flex align-items-center mb-2">
                                    <i class="fas fa-${statusIcon} ${statusClass} me-2"></i>
                                    <code class="flex-grow-1">${cmd.command}</code>
                                </div>
                                <pre class="bg-light p-2 mb-0 ${statusClass}">${cmd.output || 'No output'}</pre>
                            </div>
                        `;
                    });
                } else {
                    html += '<div class="alert alert-info">No commands were executed.</div>';
                }
                
                html += `
                        </div>
                    </div>
                </div>
            `;
        }
    } else if (!result.errors) {
        html += '<div class="alert alert-info">No results available.</div>';
    }
    
    html += '</div>';
    return html;
}

// Format query response
function formatQueryResponse(data) {
    let html = '<div class="query-results">';
    
    for (const [server, info] of Object.entries(data.results || {})) {
        html += `
            <div class="card mb-3">
                <div class="card-header">
                    <h6 class="mb-0">
                        <i class="fas fa-server me-2"></i>${server}
                        <small class="text-muted">(${info.ip})</small>
                    </h6>
                </div>
                <div class="card-body">
                    <h6>Services: ${info.services.join(', ')}</h6>
                    <hr>
                    <div class="command-outputs">
        `;
        
        for (const cmd of info.commands.commands || []) {
            const statusClass = cmd.success ? 'text-success' : 'text-danger';
            html += `
                <div class="command-output mb-3">
                    <code class="d-block mb-2">$ ${cmd.command}</code>
                    <pre class="bg-light p-2 ${statusClass}">${cmd.output}</pre>
                </div>
            `;
        }
        
        html += `
                    </div>
                </div>
            </div>
        `;
    }
    
    html += '</div>';
    return html;
}

// Format resolution response
function formatResolutionResponse(data) {
    const resolution = data.resolution;
    const validation = data.validation;
    
    let html = `
        <div class="resolution-plan">
            <div class="alert alert-info">
                <h6>Issue Summary</h6>
                <p>${resolution.issue_summary}</p>
            </div>
            
            <div class="card mb-3">
                <div class="card-header">
                    <h6 class="mb-0">Resolution Plan</h6>
                </div>
                <div class="card-body">
                    <p><strong>Target:</strong> ${resolution.service} on ${resolution.server}</p>
                    <p><strong>Severity:</strong> ${resolution.severity}</p>
                    
                    <h6 class="mt-3">Steps:</h6>
                    <ol class="steps-list">
    `;
    
    for (const step of resolution.resolution_steps) {
        html += `
            <li class="mb-3">
                <div><strong>Action:</strong> <code>${step.step}</code></div>
                <div><strong>Purpose:</strong> ${step.purpose}</div>
                <div><strong>Validation:</strong> ${step.validation}</div>
                <div><strong>Rollback:</strong> <code>${step.rollback}</code></div>
            </li>
        `;
    }
    
    html += `
                    </ol>
                    
                    <h6 class="mt-3">Risks:</h6>
                    <ul>
                        ${resolution.risks.map(risk => `<li>${risk}</li>`).join('')}
                    </ul>
                    
                    <h6 class="mt-3">Prerequisites:</h6>
                    <ul>
                        ${resolution.prerequisites.map(req => `<li>${req}</li>`).join('')}
                    </ul>
                </div>
            </div>
    `;
    
    if (validation) {
        const validationClass = validation.approved ? 'alert-success' : 'alert-warning';
        html += `
            <div class="alert ${validationClass}">
                <h6>Validation Result</h6>
                <p>${validation.reason}</p>
                ${validation.risks_identified.length > 0 ? `
                    <h6 class="mt-3">Risks Identified:</h6>
                    <ul>
                        ${validation.risks_identified.map(risk => `<li>${risk}</li>`).join('')}
                    </ul>
                ` : ''}
                ${validation.suggested_modifications.length > 0 ? `
                    <h6 class="mt-3">Suggested Modifications:</h6>
                    <ul>
                        ${validation.suggested_modifications.map(mod => `<li>${mod}</li>`).join('')}
                    </ul>
                ` : ''}
            </div>
        `;
    }
    
    html += '</div>';
    return html;
}

// Approve and execute resolution
async function approveExecution() {
    if (!currentTicketId || !currentExecutionData) {
        showError('No execution data available');
        return;
    }
    
    const approveButton = document.querySelector('#executionApproval .btn-success');
    const rejectButton = document.querySelector('#executionApproval .btn-danger');
    
    try {
        // Disable buttons and show loading state
        approveButton.disabled = true;
        rejectButton.disabled = true;
        approveButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Executing...';
        
        // Submit execution approval
        const response = await fetch('/approve_execution', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `ticket_id=${encodeURIComponent(currentTicketId)}&execution_data=${encodeURIComponent(JSON.stringify(currentExecutionData))}`
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            showExecutionResults(result.data);
        } else {
            showError(result.message);
        }
    } catch (error) {
        showError('Failed to execute resolution: ' + error.message);
    } finally {
        // Reset buttons
        approveButton.disabled = false;
        rejectButton.disabled = false;
        approveButton.innerHTML = '<i class="fas fa-check me-2"></i>Approve & Execute';
    }
}

// Reject execution
function rejectExecution() {
    const executionApproval = document.getElementById('executionApproval');
    executionApproval.classList.add('d-none');
    currentTicketId = null;
    currentExecutionData = null;
}

// Show execution results
function showExecutionResults(data) {
    const responseContent = document.getElementById('responseContent');
    const executionApproval = document.getElementById('executionApproval');
    
    let html = `
        <div class="execution-results">
            <h5>Execution Results</h5>
            <div class="timeline">
    `;
    
    for (const result of data.results) {
        const statusClass = result.success ? 'text-success' : 'text-danger';
        const icon = result.success ? 'check-circle' : 'times-circle';
        
        html += `
            <div class="timeline-item">
                <div class="timeline-badge ${statusClass}">
                    <i class="fas fa-${icon}"></i>
                </div>
                <div class="timeline-content">
                    <h6>${result.step}</h6>
                    <pre class="bg-light p-2">${result.output}</pre>
                    ${result.validation ? `
                        <div class="mt-2">
                            <strong>Validation:</strong>
                            <pre class="bg-light p-2">${result.validation.output}</pre>
                        </div>
                    ` : ''}
                    ${result.rollback_result ? `
                        <div class="mt-2 text-warning">
                            <strong>Rollback Executed:</strong>
                            <pre class="bg-light p-2">${result.rollback_result.output}</pre>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
    
    html += `
            </div>
        </div>
    `;
    
    responseContent.innerHTML = html;
    executionApproval.classList.add('d-none');
    
    // Reset current execution data
    currentTicketId = null;
    currentExecutionData = null;
}

// Show error message
function showError(message) {
    const responseArea = document.getElementById('responseArea');
    const responseContent = document.getElementById('responseContent');
    const executionApproval = document.getElementById('executionApproval');
    
    responseArea.classList.remove('d-none');
    responseContent.innerHTML = `
        <div class="alert alert-danger">
            <i class="fas fa-exclamation-circle me-2"></i>${message}
        </div>
    `;
    executionApproval.classList.add('d-none');
}

// View ticket details
async function viewTicketDetails(ticketId) {
    try {
        const response = await fetch(`/ticket/${ticketId}`);
        const result = await response.json();
        
        if (result.status === 'success') {
            const ticketModal = new bootstrap.Modal(document.getElementById('ticketModal'));
            document.getElementById('ticketDetails').innerHTML = formatTicketDetails(result.data);
            ticketModal.show();
        } else {
            showError(result.message);
        }
    } catch (error) {
        showError('Failed to load ticket details: ' + error.message);
    }
}

// Format knowledge query response
function formatKnowledgeResponse(data) {
    let html = '<div class="knowledge-results">';
    
    if (data.response) {
        // Convert markdown to HTML
        const converter = new showdown.Converter();
        html += converter.makeHtml(data.response);
    } else {
        html += '<p class="text-muted">No information available.</p>';
    }
    
    html += '</div>';
    return html;
}

// Format ticket details
function formatTicketDetails(ticket) {
    return `
        <div class="ticket-details">
            <div class="mb-3">
                <h6>Issue Description</h6>
                <p>${ticket.issue}</p>
            </div>
            
            <div class="mb-3">
                <h6>Category</h6>
                <span class="badge ${getBadgeClass(ticket.type)}">
                    ${ticket.type}
                </span>
            </div>
            
            <div class="mb-3">
                <h6>Classification Reason</h6>
                <p>${ticket.classification_reason}</p>
            </div>
            
            ${ticket.type === 'knowledge_query' ? `
                <div class="mb-3">
                    <h6>Knowledge Response</h6>
                    ${formatKnowledgeResponse(ticket.data)}
                </div>
            ` : ''}
            
            ${ticket.type === 'api_query' ? `
                <div class="mb-3">
                    <h6>API Information</h6>
                    ${formatApiResponse(ticket.data)}
                </div>
            ` : ''}
            
            ${ticket.type === 'infrastructure_query' ? `
                <div class="mb-3">
                    <h6>Infrastructure Status</h6>
                    ${formatQueryResponse(ticket.data)}
                </div>
            ` : ''}
            
            ${ticket.type === 'resolution' ? `
                <div class="mb-3">
                    <h6>Resolution Plan</h6>
                    ${formatResolutionResponse(ticket.data)}
                </div>
            ` : ''}
        </div>
    `;
}

// Helper function to get badge class based on response type
function getBadgeClass(type) {
    const classes = {
        'knowledge_query': 'bg-info',
        'api_query': 'bg-primary',
        'infrastructure_query': 'bg-success',
        'resolution': 'bg-warning'
    };
    return classes[type] || 'bg-secondary';
}

// Initialize tooltips and popovers
document.addEventListener('DOMContentLoaded', function() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function(popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
}); 