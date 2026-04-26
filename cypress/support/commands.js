// Custom Cypress commands for RetailFixIt AI-VRS

/**
 * cy.login(email, password)
 * Reusable login command — use this in other test files
 * instead of repeating the login steps.
 *
 * Example:
 *   cy.login('munamazon0@gmail.com', 'Mun1234@')
 */
Cypress.Commands.add('login', (email, password) => {
  cy.visit('/auth')
  cy.get('input[type="email"]').type(email)
  cy.get('input[type="password"]').type(password)
  cy.get('button[type="submit"]').click()
  cy.url().should('include', '/dashboard')
})
