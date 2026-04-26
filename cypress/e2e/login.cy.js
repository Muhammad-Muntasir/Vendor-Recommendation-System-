/**
 * E2E Login Tests for RetailFixIt AI-VRS
 *
 * Prerequisites:
 *   1. Frontend dev server running: npm run dev --prefix frontend
 *   2. Valid confirmed Cognito account exists
 *
 * Run with:
 *   npx cypress open        (interactive mode)
 *   npx cypress run         (headless mode)
 */

describe('RetailFixIt Login', () => {

  beforeEach(() => {
    // Visit the auth page before each test
    cy.visit('/auth')
  })

  // ── Test 1: Successful login ──────────────────────────────────────────────
  it('logs in with valid credentials and redirects to dashboard', () => {
    // Make sure we are on the Login tab (it's the default)
    cy.contains('button', 'Login').click()

    // Type email into the email input field
    cy.get('input[type="email"]').type('munamazon0@gmail.com')

    // Type password into the password input field
    cy.get('input[type="password"]').type('Mun1234@')

    // Click the Sign In button
    cy.get('button[type="submit"]').click()

    // After login, should redirect to /dashboard
    cy.url().should('include', '/dashboard')

    // Dashboard page should show the RetailFixIt header
    cy.contains('RetailFixIt').should('be.visible')

    // Dashboard heading should be visible
    cy.contains('Dashboard').should('be.visible')
  })

  // ── Test 2: Wrong password shows error ───────────────────────────────────
  it('shows error message for wrong password', () => {
    cy.contains('button', 'Login').click()

    cy.get('input[type="email"]').type('munamazon0@gmail.com')
    cy.get('input[type="password"]').type('WrongPassword123!')

    cy.get('button[type="submit"]').click()

    // Error message should appear — email field should NOT be cleared
    cy.get('input[type="email"]').should('have.value', 'munamazon0@gmail.com')
    cy.get('[role="alert"]').should('be.visible')
  })

  // ── Test 3: Empty fields show browser validation ──────────────────────────
  it('does not submit with empty email', () => {
    cy.contains('button', 'Login').click()

    // Leave email empty, fill password
    cy.get('input[type="password"]').type('Mun1234@')
    cy.get('button[type="submit"]').click()

    // Should still be on /auth (form not submitted)
    cy.url().should('include', '/auth')
  })

  // ── Test 4: Register tab is visible ──────────────────────────────────────
  it('shows Register tab and form fields', () => {
    cy.contains('button', 'Register').click()

    // Register form should have email, password, confirm password
    cy.get('input[type="email"]').should('be.visible')
    cy.get('input[type="password"]').should('have.length.at.least', 2)
    cy.contains('button', 'Create Account').should('be.visible')
  })

  // ── Test 5: Logout works ─────────────────────────────────────────────────
  it('logs in then logs out successfully', () => {
    cy.get('input[type="email"]').type('munamazon0@gmail.com')
    cy.get('input[type="password"]').type('Mun1234@')
    cy.get('button[type="submit"]').click()

    // Wait for dashboard
    cy.url().should('include', '/dashboard')

    // Click logout button in the header
    cy.contains('button', 'Logout').click()

    // Should redirect back to /auth
    cy.url().should('include', '/auth')
  })

})
