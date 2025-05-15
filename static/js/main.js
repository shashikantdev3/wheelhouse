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
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.message || `HTTP error! status: ${response.status}`);
        }
        
        // Update ticket history if available
        if (result.ticket_log) {
            updateTicketHistory(result.ticket_log);
        }
        
        if (result.status === 'success') {
            showResponse(result);
            form.reset();
        } else {
            showError(result.message || result.error || 'Unknown error occurred');
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

// Update ticket history table
function updateTicketHistory(tickets) {
    const ticketLog = document.getElementById('ticketLog');
    if (!ticketLog) return;
    
    ticketLog.innerHTML = tickets.map(ticket => `
        <tr>
            <td>${new Date(ticket.timestamp).toLocaleString()}</td>
            <td>${ticket.issue.substring(0, 50)}${ticket.issue.length > 50 ? '...' : ''}</td>
            <td>
                <span class="badge ${getBadgeClass(ticket.category)}">
                    ${ticket.category || 'unknown'}
                </span>
            </td>
            <td>
                <span class="badge ${getStatusBadgeClass(ticket.status)}">
                    ${ticket.status || 'unknown'}
                </span>
            </td>
            <td>
                <button class="btn btn-sm btn-info" onclick="viewTicketDetails('${ticket.id}')">
                    <i class="fas fa-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

// Get badge class for ticket category
function getBadgeClass(category) {
    switch (category) {
        case 'general_query':
            return 'bg-info';
        case 'knowledge_query':
            return 'bg-primary';
        case 'api_query':
            return 'bg-success';
        case 'needs_resolution':
            return 'bg-warning';
        default:
            return 'bg-secondary';
    }
}

// Get badge class for ticket status
function getStatusBadgeClass(status) {
    switch (status) {
        case 'completed':
            return 'bg-success';
        case 'error':
            return 'bg-danger';
        case 'processing':
            return 'bg-info';
        default:
            return 'bg-secondary';
    }
}

// Display response in the UI
function showResponse(result) {
    const responseArea = document.getElementById('responseArea');
    const responseContent = document.getElementById('responseContent');
    const executionApproval = document.getElementById('executionApproval');
    
    responseArea.classList.remove('d-none');
    
    // Add detailed console logging to help diagnose response structure issues
    console.log('Raw response:', result);
    console.log('Response type:', result.type);
    console.log('Response status:', result.status);
    console.log('Response structure:', Object.keys(result));
    
    let content = '';
    console.log('Processing response:', result);  // Debug log
    
    switch (result.type) {
        case 'infrastructure_query':
            content = formatInfrastructureResponse(result);
            break;
        case 'knowledge_query':
            console.log('Knowledge query data:', result.results);  // Updated to log the correct field
            content = formatKnowledgeResponse(result.results);  // Changed from result.data to result.results
            break;
        case 'api_query':
            content = formatApiResponse(result);
            break;
        case 'resolution':
            content = formatResolutionResponse(result.data);
            // Store execution data for later use
            if (result.data?.resolution) {
                currentTicketId = result.data.ticketId;
                currentExecutionData = result.data.resolution;
                if (result.data?.validation?.approved) {
                    executionApproval.classList.remove('d-none');
                }
            }
            break;
        default:
            content = `<div class="alert alert-warning">Unsupported response type: ${result.type}</div>`;
    }
    
    responseContent.innerHTML = content;
    
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
    
    // Show server results in cards
    if (result.data && result.data.length > 0) {
        result.data.forEach(serverData => {
            const statusBadge = serverData.status === 'success' 
                ? '<span class="badge bg-success">Success</span>' 
                : '<span class="badge bg-danger">Error</span>';
                
            html += `
                <div class="card mb-3">
                    <div class="card-header bg-light">
                        <div class="d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">
                                <i class="fas fa-server me-2"></i>${serverData.server}
                                <small class="text-muted">(${serverData.ip})</small>
                            </h6>
                            ${statusBadge}
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="d-flex justify-content-between mb-2">
                            <span><strong>Services:</strong> ${serverData.services.join(', ')}</span>
                        </div>`;
                
            // Add command output with syntax highlighting
            if (serverData.output && serverData.output.trim()) {
                html += `
                    <div class="command-output mt-3">
                        <div class="card">
                            <div class="card-header bg-dark text-light py-1">
                                <small>Command Output</small>
                            </div>
                            <div class="card-body bg-dark text-light p-3">
                                <pre class="mb-0" style="color: #d3d3d3; white-space: pre-wrap;">${escapeHtml(serverData.output)}</pre>
                            </div>
                        </div>
                    </div>`;
            } else {
                html += `
                    <div class="alert alert-warning mt-3 mb-0">
                        No commands were executed.
                    </div>`;
            }
                
            html += `
                    </div>
                </div>`;
        });
    } else if (result.results && Object.keys(result.results).length > 0) {
        // Fallback to old format if new format not available
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
                        <div class="command-outputs">`;
                
            const commands = info.commands || [];
            if (commands.length > 0) {
                commands.forEach(cmd => {
                    const statusClass = cmd.success ? 'text-success' : 'text-danger';
                    const statusIcon = cmd.success ? 'check-circle' : 'times-circle';
                    html += `
                        <div class="command-output mb-3">
                            <div class="d-flex align-items-center mb-2">
                                <i class="fas fa-${statusIcon} ${statusClass} me-2"></i>
                                <span class="command-label">${cmd.command || 'Command'}</span>
                            </div>
                            <pre class="command-result bg-dark text-light p-3 rounded">${escapeHtml(cmd.output)}</pre>
                        </div>`;
                });
            } else {
                html += `<div class="alert alert-warning mb-0">No commands were executed.</div>`;
            }
                
            html += `
                        </div>
                    </div>
                </div>`;
        }
    } else {
        html += `<div class="alert alert-info">No server data available.</div>`;
    }
    
    html += '</div>';
    return html;
}

// Helper function to escape HTML
function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
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
    const execution = data.execution;
    
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
                <div><strong>Action:</strong> ${step.step}</div>
                <div><strong>Purpose:</strong> ${step.purpose}</div>
                <div><strong>Validation:</strong> <code>${step.validation}</code></div>
                ${step.rollback ? `<div><strong>Rollback:</strong> <code>${step.rollback}</code></div>` : ''}
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

    // Add validation information
    if (validation) {
        const validationClass = validation.approved ? 'success' : 'warning';
        const validationIcon = validation.approved ? 'check-circle' : 'exclamation-triangle';
        
        html += `
            <div class="card mb-3">
                <div class="card-header bg-${validationClass} text-white">
                    <h6 class="mb-0">
                        <i class="fas fa-${validationIcon} me-2"></i>Validation Result
                    </h6>
                </div>
                <div class="card-body">
                    <p><strong>Status:</strong> ${validation.approved ? 'Approved' : 'Needs Review'}</p>
                    <p><strong>Confidence:</strong> ${(validation.confidence * 100).toFixed(1)}%</p>
                    <p><strong>Reason:</strong> ${validation.reason}</p>
                    
                    ${validation.risks_identified.length > 0 ? `
                        <h6 class="mt-3">Identified Risks:</h6>
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
            </div>
        `;
    }

    // Add execution results if available
    if (execution && Object.keys(execution).length > 0) {
        html += formatExecutionResults(execution);
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
            showError(result.message || 'Execution failed');
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

// Format execution results
function formatExecutionResults(execution) {
    let html = `
        <div class="card mb-3">
            <div class="card-header bg-${execution.successful ? 'success' : 'danger'} text-white">
                <h6 class="mb-0">
                    <i class="fas fa-${execution.successful ? 'check' : 'times'} me-2"></i>
                    Execution Results
                </h6>
            </div>
            <div class="card-body">
                <p><strong>Status:</strong> ${execution.successful ? 'Successful' : 'Failed'}</p>
                <p><strong>Server:</strong> ${execution.server}</p>
                <p><strong>Service:</strong> ${execution.service}</p>
                <p><strong>Timestamp:</strong> ${new Date(execution.timestamp).toLocaleString()}</p>
                
                <h6 class="mt-3">Step Results:</h6>
                <div class="step-results">
    `;
    
    for (const result of execution.results) {
        const statusClass = result.result.success ? 'success' : 'danger';
        const statusIcon = result.result.success ? 'check-circle' : 'times-circle';
        
        html += `
            <div class="card mb-2">
                <div class="card-header bg-${statusClass} bg-opacity-25">
                    <h6 class="mb-0">
                        <i class="fas fa-${statusIcon} text-${statusClass} me-2"></i>
                        ${result.step}
                    </h6>
                </div>
                <div class="card-body">
                    <p><strong>Command:</strong> <code>${result.command}</code></p>
                    <div class="output-box bg-light p-2 mb-2">
                        <pre class="mb-0">${result.result.output || 'No output'}</pre>
                    </div>
                    ${result.rollback_result ? `
                        <div class="alert alert-warning">
                            <strong>Rollback Executed:</strong>
                            <pre class="mb-0">${result.rollback_result.output || 'No output'}</pre>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
    
    html += `
                </div>
            </div>
        </div>
    `;
    
    return html;
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
    
    // Reset execution data
    currentTicketId = null;
    currentExecutionData = null;
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
    console.log('Formatting knowledge response:', data);  // Debug log
    
    if (!data || typeof data !== 'object') {
        console.warn('Invalid knowledge response data:', data);  // Debug log
        return '<div class="alert alert-warning">No information available</div>';
    }

    // Make the function more robust by checking for both data formats
    const summary = data.summary || (data.results && data.results.summary) || '';
    const source = data.source || (data.results && data.results.source) || 'web search';
    const relatedTopics = data.related_topics || (data.results && data.results.related_topics) || [];
    
    console.log('Extracted data:', { summary, source, relatedTopics });

    let html = '<div class="knowledge-response">';
    
    // Determine icon and header based on source
    let sourceIcon = 'fas fa-globe';
    let sourceText = 'Web Search Result';
    
    if (source === 'built-in knowledge base') {
        sourceIcon = 'fas fa-database';
        sourceText = 'IT Knowledge Base';
    } else if (source === 'llm_knowledge') {
        sourceIcon = 'fas fa-brain';
        sourceText = 'AI Knowledge Response';
    }
    
    html += `
        <div class="card mb-3">
            <div class="card-header bg-primary text-white">
                <h6 class="mb-0"><i class="${sourceIcon} me-2"></i>${sourceText}</h6>
            </div>
            <div class="card-body">
                <div class="mb-0">${summary}</div>
            </div>
        </div>
    `;
    
    // Handle related topics if any
    if (relatedTopics.length > 0) {
        html += `
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="fas fa-list me-2"></i>Related Topics</h6>
                </div>
                <ul class="list-group list-group-flush">
                    ${relatedTopics.map(topic => `
                        <li class="list-group-item">
                            <i class="fas fa-angle-right me-2"></i>
                            ${topic.text || topic}
                            ${topic.url ? `<a href="${topic.url}" target="_blank" class="ms-2"><i class="fas fa-external-link-alt"></i></a>` : ''}
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }
    
    html += '</div>';
    console.log('Generated HTML:', html);  // Debug log
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

// Format API response
function formatApiResponse(result) {
    if (!result || !result.response) {
        return '<div class="alert alert-warning">No API information available</div>';
    }

    const response = result.response;
    let html = '<div class="api-response">';

    // Parse the response content which is in markdown format
    const sections = response.split('###').filter(Boolean);
    
    for (const section of sections) {
        const [title, ...content] = section.trim().split('\n');
        const sectionContent = content.join('\n').trim();
        
        html += `
            <div class="card mb-3">
                <div class="card-header bg-primary text-white">
                    <h6 class="mb-0"><i class="fas fa-info-circle me-2"></i>${title}</h6>
                </div>
                <div class="card-body">
        `;

        if (title.toLowerCase().includes('base url')) {
            html += `<code>${sectionContent.replace('`', '').replace('`', '')}</code>`;
        } else if (title.toLowerCase().includes('common endpoints')) {
            const endpoints = sectionContent.split('\n').filter(line => line.trim().startsWith('-'));
            html += `
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Endpoint</th>
                                <th>Path</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            for (const endpoint of endpoints) {
                const [name, path] = endpoint.substring(2).split(':').map(s => s.trim());
                html += `
                    <tr>
                        <td><strong>${name}</strong></td>
                        <td><code>${path}</code></td>
                    </tr>
                `;
            }
            
            html += `
                        </tbody>
                    </table>
                </div>
            `;
        } else {
            html += `<p class="mb-0">${sectionContent}</p>`;
        }

        html += `
                </div>
            </div>
        `;
    }

    html += '</div>';
    return html;
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