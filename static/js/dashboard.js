document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('authToken');
    const user = JSON.parse(localStorage.getItem('currentUser'));

    if (!token) {
        window.location.href = '/login.html';
        return;
    }

    // Initialize the dashboard
    if (user) {
        document.getElementById('userName').textContent = user.name;
    }
    
    // Fetch initial data and update the UI
    fetchProfile();
    fetchStatsAndRenderCharts();

    // Event Listeners for navigation
    document.querySelectorAll('.sidebar nav a').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const sectionId = e.target.getAttribute('data-section');
            showSection(sectionId);
            
            // Re-fetch data specifically for analytics when the section is clicked
            if (sectionId === 'analytics') {
                fetchStatsAndRenderCharts();
            }
        });
    });

    // Event listener for the analytics date range selector
    document.getElementById('analyticsRange').addEventListener('change', (e) => {
        fetchStatsAndRenderCharts(e.target.value);
    });

    // Event listener for the "Apply" button to filter data
    document.getElementById('applyFilter').addEventListener('click', () => {
        const selectedRange = document.getElementById('rangeSelect').value;
        fetchStatsAndRenderCharts(selectedRange);
    });

    // Event listener for the logout button
    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.removeItem('authToken');
        localStorage.removeItem('currentUser');
        window.location.href = '/login.html';
    });

    // Event listener for saving a new entry
    document.getElementById('saveEntry').addEventListener('click', saveEntry);

  // Event listeners for subscription upgrade buttons
document.getElementById('upgradePremium').addEventListener('click', () => {
    manageSubscription('premium');
});

document.getElementById('upgradeEnterprise').addEventListener('click', () => {
    manageSubscription('enterprise');
});

// Event listener for the free plan button to handle downgrades
document.getElementById('freePlan').addEventListener('click', () => {
    const isDowngradeButton = document.getElementById('freePlan').textContent.includes('Downgrade');
    if (isDowngradeButton) {
        manageSubscription('free');
    }
});

    // Initial section display
    showSection('overview');
});

// Helper function to show a specific section
function showSection(sectionId) {
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
    document.querySelectorAll('.sidebar nav a').forEach(link => {
        link.classList.remove('active');
    });

    document.getElementById(sectionId).style.display = 'block';
    document.querySelector(`a[data-section="${sectionId}"]`).classList.add('active');
}

// Function to fetch user profile information and update UI
async function fetchProfile() {
    const token = localStorage.getItem('authToken');
    try {
        const response = await fetch('/api/profile', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (response.ok) {
            const data = await response.json();
            const plan = data.plan;
            const usage = data.usage;

            const planNameEl = document.getElementById('planName');
            planNameEl.textContent = plan.name;
            planNameEl.className = `plan-badge ${plan.name.toLowerCase()}`;
            
            document.getElementById('entriesCount').textContent = usage.entries_this_month;
            document.getElementById('entriesLimit').textContent = plan.max_entries;
            
            // NOTE: For demonstration, we'll simulate an expired subscription here.
            // In a real application, this would come from the backend, e.g., data.subscription_expired.
            const subscriptionExpired = false;
            updateSubscriptionUI(plan.name.toLowerCase(), subscriptionExpired);
        }
    } catch (error) {
        console.error('Error fetching profile:', error);
    }
}

// Function to handle the subscription upgrade and downgrade API call
async function manageSubscription(planTier) {
    const token = localStorage.getItem('authToken');
    if (!token) {
        alert("You must be logged in to manage subscriptions.");
        window.location.href = '/login.html';
        return;
    }

    // Downgrade to free plan handled locally
    if (planTier === 'free') {
        const response = await fetch('/api/subscription/upgrade', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ plan: planTier })
        });
        if (response.ok) {
            alert('Your plan has been downgraded to Free.');
            fetchProfile(); // Refresh profile UI
        } else {
            const error = await response.json();
            alert(error.error || 'Failed to downgrade plan.');
        }
        return;
    }

    try {
        const response = await fetch('/api/subscription/upgrade', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ plan: planTier })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to initiate payment.');
        }

        const data = await response.json();
        if (data.link) {
            // Redirect the user to the Paystack payment page
            window.location.href = data.link;
        } else {
            alert('Failed to get a payment link. Please try again.');
        }

    } catch (error) {
        console.error('Payment error:', error);
        alert(error.message);
    }
}


// Function to update the subscription UI
function updateSubscriptionUI(currentPlan, isExpired) {
    // Reset all buttons to a default state
    document.getElementById('freePlan').disabled = false;
    document.getElementById('freePlan').textContent = 'Free Plan';
    document.getElementById('upgradePremium').disabled = false;
    document.getElementById('upgradePremium').textContent = 'Upgrade to Premium';
    document.getElementById('upgradeEnterprise').disabled = false;
    document.getElementById('upgradeEnterprise').textContent = 'Upgrade to Enterprise';
    
    // Set the state for the current plan
    if (currentPlan === 'free') {
        document.getElementById('freePlan').disabled = true;
        document.getElementById('freePlan').textContent = 'Current Plan';
    } else if (currentPlan === 'premium') {
        if (isExpired) {
            document.getElementById('freePlan').textContent = 'Downgrade to Free';
            document.getElementById('upgradePremium').textContent = 'Upgrade to Premium';
        } else {
            document.getElementById('upgradePremium').disabled = true;
            document.getElementById('upgradePremium').textContent = 'Current Plan';
            document.getElementById('freePlan').textContent = 'Downgrade';
        }
    } else if (currentPlan === 'enterprise') {
        if (isExpired) {
            document.getElementById('freePlan').textContent = 'Downgrade to Free';
            document.getElementById('upgradeEnterprise').textContent = 'Upgrade to Enterprise';
        } else {
            document.getElementById('upgradeEnterprise').disabled = true;
            document.getElementById('upgradeEnterprise').textContent = 'Current Plan';
            document.getElementById('freePlan').textContent = 'Downgrade';
            document.getElementById('upgradePremium').textContent = 'Downgrade';
        }
    }
}


// Function to fetch and render all stats and charts
async function fetchStatsAndRenderCharts(days = 30) {
    const token = localStorage.getItem('authToken');
    const analyticsRangeEl = document.getElementById('analyticsRange');
    
    // Ensure the days value is either from the argument or the select element
    const selectedDays = analyticsRangeEl ? analyticsRangeEl.value : days;

    try {
        const response = await fetch(`/api/stats?days=${selectedDays}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) {
            throw new Error('Failed to fetch stats');
        }

        const statsData = await response.json();
        
        // Update stat cards
        document.getElementById('statTotal').textContent = statsData.total_entries;
        document.getElementById('statMonth').textContent = statsData.monthly_entries;
        document.getElementById('statEmotion').textContent = statsData.top_emotion;
        document.getElementById('statScore').textContent = `${statsData.avg_score.toFixed(2)}%`;
        
        // Render all charts
        renderMoodTrendChart(statsData.mood_trend);
        renderEmotionDistributionChart(statsData.emotion_distribution);
        renderWeeklyMoodChart(statsData.weekly_mood_pattern);
        renderEmotionCorrelationChart(statsData.emotion_correlation);

        // Generate and display insights
        document.getElementById('insightsContent').innerHTML = generateInsights(statsData);

    } catch (error) {
        console.error('Error fetching stats:', error);
    }
}

// Function to save a new journal entry
async function saveEntry() {
    const content = document.getElementById('content').value.trim();
    if (!content) {
        alert('Please write something before saving.');
        return;
    }

    const token = localStorage.getItem('authToken');
    try {
        const response = await fetch('/api/entries', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ content })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to save entry');
        }

        document.getElementById('content').value = '';
        alert('Entry saved successfully!');
        fetchStatsAndRenderCharts();
    } catch (error) {
        console.error('Error saving entry:', error);
        alert(error.message);
    }
}

// New function to generate insights
function generateInsights(statsData) {
    const totalEntries = statsData.total_entries;
    const insightsContent = document.getElementById('insightsContent');

    if (totalEntries < 5) {
        return `<p>Keep writing! Your insights will appear here after we analyze more of your entries.</p>`;
    }

    let insightsHTML = '';

    // Insight 1: Overall Mood
    const avgScore = statsData.avg_score;
    let moodInsight = '';
    if (avgScore > 75) {
        moodInsight = `Your overall mood has been **very positive**, averaging a score of **${avgScore.toFixed(2)}%** in this period. Great job on maintaining a high emotional state!`;
    } else if (avgScore > 50) {
        moodInsight = `Your overall mood has been **generally positive**, averaging a score of **${avgScore.toFixed(2)}%**. This is a great baseline!`;
    } else {
        moodInsight = `Your overall mood has been **neutral to low**, averaging a score of **${avgScore.toFixed(2)}%**. Consider reflecting on what might be causing this trend.`;
    }
    insightsHTML += `<p>📊 **Overall Mood**: ${moodInsight}</p>`;

    // Insight 2: Top Emotion
    const topEmotion = statsData.top_emotion;
    insightsHTML += `<p>🎯 **Top Emotion**: The emotion you've expressed most frequently is **${topEmotion}**. This is a central theme in your recent entries.</p>`;

    // Insight 3: Weekly Mood Pattern
    const weeklyPattern = statsData.weekly_mood_pattern;
    const maxDay = weeklyPattern.reduce((max, day) => day.average_score > max.average_score ? day : max, weeklyPattern[0]);
    const minDay = weeklyPattern.reduce((min, day) => day.average_score < min.average_score ? day : min, weeklyPattern[0]);
    insightsHTML += `<p>📅 **Weekly Pattern**: Your mood tends to be highest on **${maxDay.day}** and lowest on **${minDay.day}**. This might indicate a recurring weekly cycle or a pattern related to your schedule.</p>`;
    
    // Insight 4: Emotion Correlation
    const emotionCorrelation = statsData.emotion_correlation;
    if (emotionCorrelation.length > 0) {
        const topPair = emotionCorrelation[0];
        insightsHTML += `<p>🔗 **Emotion Correlation**: You most frequently express the emotions **${topPair.pair}** together. This suggests these feelings are closely linked in your journal entries.</p>`;
    }

    return insightsHTML;
}

// Chart rendering functions
function renderMoodTrendChart(moodTrendData) {
    const ctx = document.getElementById('moodTrendChart').getContext('2d');
    const labels = moodTrendData.map(d => d.date);
    const data = moodTrendData.map(d => d.average_score);
    
    if (Chart.getChart('moodTrendChart')) {
        Chart.getChart('moodTrendChart').destroy();
    }

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Average Mood Score',
                data: data,
                borderColor: '#4299e1',
                tension: 0.1,
                fill: false
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Score' } },
                x: { title: { display: true, text: 'Date' } }
            }
        }
    });
}

function renderEmotionDistributionChart(emotionDistributionData) {
    const ctx = document.getElementById('emotionDistributionChart').getContext('2d');
    const labels = emotionDistributionData.map(d => `${d.label} ${d.emoji}`);
    const data = emotionDistributionData.map(d => d.count);
    const colors = ['#f56565', '#4fd1c5', '#f6e05e', '#68d391', '#805ad5', '#ed8936'];

    if (Chart.getChart('emotionDistributionChart')) {
        Chart.getChart('emotionDistributionChart').destroy();
    }

    new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                label: 'Emotion Count',
                data: data,
                backgroundColor: colors,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });
}

function renderWeeklyMoodChart(weeklyMoodData) {
    const ctx = document.getElementById('weeklyMoodChart').getContext('2d');
    const labels = weeklyMoodData.map(d => d.day);
    const scores = weeklyMoodData.map(d => d.average_score);
    
    if (Chart.getChart('weeklyMoodChart')) {
        Chart.getChart('weeklyMoodChart').destroy();
    }

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Average Score by Day of the Week',
                data: scores,
                backgroundColor: '#38b2ac',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, title: { display: true, text: 'Average Score' } },
                x: { title: { display: true, text: 'Day of the Week' } }
            }
        }
    });
}

function renderEmotionCorrelationChart(correlationData) {
    const ctx = document.getElementById('emotionCorrelationChart').getContext('2d');
    const labels = correlationData.map(d => d.pair);
    const data = correlationData.map(d => d.count);
    
    if (Chart.getChart('emotionCorrelationChart')) {
        Chart.getChart('emotionCorrelationChart').destroy();
    }

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Emotion Pair Frequency',
                data: data,
                backgroundColor: '#6b46c1',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            scales: {
                x: { beginAtZero: true, title: { display: true, text: 'Frequency' } },
                y: { title: { display: true, text: 'Emotion Pairs' } }
            }
        }
    });
}