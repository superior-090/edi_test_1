// first edi by shree
#include <iostream>
using namespace std;

struct node{
    int data;
    node *left, *right;

    node(int data){
        this->data = data;
        left = NULL;
        right = NULL;
    }
};

node *Insert(node * root, int data){

    if(root == NULL){
        return new node(data);
    }

    if(root->data < data){
        root->right= Insert(root->right, data);
    }
    else if(root->data > data){
        root->left = Insert(root->left, data);
    }
    
    return root;
}

void inorder(node* root){

    if(root == NULL) return;

    inorder(root->left);
    cout<<root->data<<" ";
    inorder(root->right);

}

int main() {
    node *root = NULL;
    root = Insert(root, 90);
    root = Insert(root, 60);
    root = Insert(root, 70);
    root = Insert(root, 110);
    root = Insert(root, 66);
    root = Insert(root, 50);

    inorder(root);


    return 0;
}