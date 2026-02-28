pipeline {
    agent any

    environment {
        // Local virtual environment within the Jenkins workspace for portability
        VENV_PATH = "${WORKSPACE}/.venv"
        VENV_BIN = "${VENV_PATH}/bin"
    }

    stages {
        stage('Initialize') {
            steps {
                echo 'Creating Isolated Virtual Environment...'
                sh "python3 -m venv ${VENV_PATH}"
                
                echo 'Installing Dependencies in Editable Mode...'
                sh "${VENV_BIN}/pip install --upgrade pip"
                sh "${VENV_BIN}/pip install -e .[dev]"
            }
        }

        stage('Linting') {
            parallel {
                stage('Black') {
                    steps {
                        sh "${VENV_BIN}/black --check logflow tests examples"
                    }
                }
                stage('Isort') {
                    steps {
                        sh "${VENV_BIN}/isort --check-only logflow tests examples"
                    }
                }
                stage('Flake8') {
                    steps {
                        sh "${VENV_BIN}/flake8 logflow tests examples"
                    }
                }
            }
        }

        stage('Type Check') {
            steps {
                sh "${VENV_BIN}/mypy logflow tests examples"
            }
        }

        stage('Unit Tests') {
            steps {
                sh "${VENV_BIN}/pytest tests"
            }
        }
    }

    post {
        always {
            echo 'LogFlow Pipeline Complete.'
        }
        success {
            echo 'Project is healthy and ready for publication.'
        }
        failure {
            echo 'Build failed. Please check linting or test failures.'
        }
    }
}
